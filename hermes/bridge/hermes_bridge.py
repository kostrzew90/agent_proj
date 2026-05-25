"""
Hermes Bridge daemon.

Polls /audit/inbox/ for messages from telegram-watcher,
routes RECALL: commands to semantic recall from Postgres/Ollama,
writes replies to /audit/outbox/, moves processed files to
/audit/processed/, and logs to /audit/actions.log.
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
import psycopg2
import psycopg2.extras

import memory as mem
import llm_client

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_AUDIT_DIR: Path = Path(os.environ.get("HERMES_AUDIT_DIR", "/audit"))

_POLL_INTERVAL: float = 2.0  # seconds between inbox scans

_RECALL_DSN: str = os.environ.get(
    "HERMES_RECALL_DSN",
    "postgresql://rag:ragpass@host.docker.internal:5434/rag",
)
_OLLAMA_URL: str = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")
_EMBEDDING_MODEL: str = os.environ.get("EMBEDDING_MODEL", "qwen3-embedding:0.6b")
_BRAVE_API_KEY: str = os.environ.get("BRAVE_API_KEY", "")
_N8N_WEBHOOK_URL: str = os.environ.get("N8N_WEBHOOK_URL", "")

_running: bool = True

# ---------------------------------------------------------------------------
# Cron scheduler config
# ---------------------------------------------------------------------------

_CRON_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "")
_LEGACY_ENABLED: bool = os.environ.get("HERMES_ENABLE_LEGACY_CRONS") == "1"

# Each entry: skill_name → {interval_s, hour (optional, for daily), enabled, last_run}
_CRON_JOBS: dict[str, dict] = {
    "scan-rss": {
        "interval_s": 86400,
        "run_at_hour": 8,
        "enabled": _LEGACY_ENABLED,
        "last_run": 0.0,
        "description": "Job board scan (daily 8:00)",
        "notify": "always",
    },
    "crypto-arbitrage": {
        "interval_s": 3600,
        "run_at_hour": None,
        "enabled": _LEGACY_ENABLED,
        "last_run": 0.0,
        "description": "Gate.io vs Binance spread check (hourly)",
        "notify": "on_alert",
    },
    "auto-todo": {
        "interval_s": 21600,
        "run_at_hour": None,
        "enabled": _LEGACY_ENABLED,
        "last_run": 0.0,
        "description": "Extract TODOs from recent Chrome tabs (every 6h)",
        "notify": "always",
    },
    "classify-tabs": {
        "interval_s": 21600,
        "run_at_hour": None,
        "enabled": _LEGACY_ENABLED,
        "last_run": 0.0,
        "description": "Classify uncategorized Chrome tabs (every 6h)",
        "notify": "silent",
    },
    "daily-digest": {
        "interval_s": 86400,
        "run_at_hour": 7,
        "enabled": _LEGACY_ENABLED,
        "last_run": 0.0,
        "description": "Daily activity summary (7:00)",
        "notify": "always",
    },
    "recompute-importance": {
        "interval_s": 21600,
        "run_at_hour": None,
        "enabled": _LEGACY_ENABLED,
        "last_run": 0.0,
        "description": "Recompute tab importance scores (every 6h)",
        "notify": "silent",
    },
    "check-confirmations": {
        "interval_s": 21600,
        "run_at_hour": None,
        "enabled": _LEGACY_ENABLED,
        "last_run": 0.0,
        "description": "Notify about pending domain confirmations (every 6h)",
        "notify": "on_alert",
    },
    "review-learn": {
        "interval_s": 10800,
        "run_at_hour": None,
        "enabled": _LEGACY_ENABLED,
        "last_run": 0.0,
        "description": "Review code + ask for improvements (every 3h)",
        "notify": "always",
    },
    "pool-monitor": {
        "interval_s": 1800,
        "run_at_hour": None,
        "enabled": False,
        "last_run": 0.0,
        "description": "Basen Nieporęt — liczba osób co 30 min (wyłączony — przejęty przez GitHub Actions → Neon)",
        "notify": "silent",
    },
    "scrape-autocentrum": {
        "interval_s": 86400,
        "run_at_hour": 2,
        "enabled": True,
        "last_run": 0.0,
        "description": "Scrape autocentrum.pl reviews + opinions (daily 2:00)",
        "notify": "silent",
    },
    "vinhunter-researcher": {
        "interval_s": 86400,
        "run_at_hour": 10,
        "enabled": True,
        "last_run": 0.0,
        "description": "Research new VIN data sources (weekly, 10:00)",
        "notify": "always",
    },
}

_cron_lock = threading.Lock()
_LAST_POOL_MONITOR: dict = {"ok": None, "last_run": None, "count": None}

_AUTOCENTRUM_QUEUE_FILE: Path = _AUDIT_DIR / "autocentrum_queue.json"

_AUTOCENTRUM_SEED: list[dict] = [
    {"make": "BMW", "model": "Seria 3", "done": False},
    {"make": "BMW", "model": "Seria 5", "done": False},
    {"make": "Audi", "model": "A4", "done": False},
    {"make": "Audi", "model": "A6", "done": False},
    {"make": "Volkswagen", "model": "Passat", "done": False},
    {"make": "Volkswagen", "model": "Golf", "done": False},
    {"make": "Mercedes-Benz", "model": "Klasa C", "done": False},
    {"make": "Toyota", "model": "Avensis", "done": False},
    {"make": "Toyota", "model": "Corolla", "done": False},
    {"make": "Opel", "model": "Astra", "done": False},
]

# Lazy DB connection — created on first recall, not at startup.
_db_conn: Optional[Any] = None


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------

def _handle_sigterm(signum: int, frame: object) -> None:
    global _running
    print("[bridge] SIGTERM received — shutting down after current iteration", flush=True)
    _running = False


signal.signal(signal.SIGTERM, _handle_sigterm)


# ---------------------------------------------------------------------------
# Directory helpers
# ---------------------------------------------------------------------------

def _inbox_dir() -> Path:
    return _AUDIT_DIR / "inbox"


def _outbox_dir() -> Path:
    return _AUDIT_DIR / "outbox"


def _processed_dir() -> Path:
    return _AUDIT_DIR / "processed"


def _actions_log() -> Path:
    return _AUDIT_DIR / "actions.log"


def _rag_queries_log() -> Path:
    return _AUDIT_DIR / "rag_queries.log"


def _research_log() -> Path:
    return _AUDIT_DIR / "research.log"


def _ensure_dirs() -> None:
    for d in (_inbox_dir(), _outbox_dir(), _processed_dir()):
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Observability helpers
# ---------------------------------------------------------------------------

def _append_rag_log(query: str, num_results: int, top_score: float, latency_ms: float) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": "recall",
        "query": query[:200],
        "num_results": num_results,
        "top_score": top_score,
        "latency_ms": round(latency_ms, 1),
    }
    with _rag_queries_log().open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _append_research_log(
    query: str,
    google_results: list,
    chatgpt_answer: str,
    divergent: bool,
    latency_ms: float,
    tier: str = "medium",
    model_used: str = "",
    llm_latency_ms: int = 0,
) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": "research",
        "query": query[:200],
        "google_count": len(google_results),
        "google_snippets": [r.get("snippet", "")[:100] for r in google_results[:3]],
        "chatgpt_preview": chatgpt_answer[:200],
        "divergent": divergent,
        "latency_ms": round(latency_ms, 1),
        "tier": tier,
        "model_used": model_used,
        "llm_latency_ms": llm_latency_ms,
    }
    with _research_log().open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Recall — semantic search from Postgres + Ollama embeddings
# ---------------------------------------------------------------------------

def _get_db_conn() -> Any:
    """Return a live psycopg2 connection, (re)creating if needed."""
    global _db_conn
    try:
        if _db_conn is not None:
            # Quick liveness check — cursor creation is cheap.
            _db_conn.cursor().close()
            return _db_conn
    except Exception:
        _db_conn = None

    _db_conn = psycopg2.connect(_RECALL_DSN)
    _db_conn.set_session(readonly=True, autocommit=True)
    return _db_conn


def _embed_query(query: str) -> list[float]:
    """Embed query text via Ollama. Returns list of floats."""
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{_OLLAMA_URL}/api/embeddings",
            json={"model": _EMBEDDING_MODEL, "prompt": query},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["embedding"]


def _handle_recall(query: str) -> str:
    """
    Embed the query, run HNSW cosine search, apply hybrid scoring, return
    formatted results as a Telegram-friendly string.
    """
    query = query.strip()
    if not query:
        return "Podaj zapytanie po /recall."

    t0 = time.monotonic()

    # 1. Embed
    try:
        embedding = _embed_query(query)
    except Exception as exc:
        print(f"[bridge] Ollama embedding error: {exc}", flush=True)
        _append_rag_log(query, 0, 0.0, (time.monotonic() - t0) * 1000)
        return f"Nie mogę połączyć się z modelem embeddingów. ({exc})"

    vec_literal = "[" + ",".join(str(x) for x in embedding) + "]"

    # 2. Query Postgres with hybrid scoring
    sql = """
        SELECT
            t.url,
            t.title,
            t.domain,
            c.text,
            ROUND((1 - (c.embedding <=> %s::vector))::numeric, 4)  AS sem_score,
            EXTRACT(EPOCH FROM (now() - t.captured_at)) / 86400.0  AS days_ago,
            COALESCE(w.base_weight, 1.0)                            AS domain_w,
            t.importance_score
        FROM hermes_tab_chunks c
        JOIN hermes_tabs t ON t.id = c.tab_id
        LEFT JOIN hermes_domain_weights w ON w.domain = t.domain
        ORDER BY c.embedding <=> %s::vector
        LIMIT 5;
    """
    try:
        conn = _get_db_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (vec_literal, vec_literal))
            rows = cur.fetchall()
    except Exception as exc:
        print(f"[bridge] DB recall error: {exc}", flush=True)
        # Invalidate connection so next call reconnects.
        global _db_conn
        _db_conn = None
        _append_rag_log(query, 0, 0.0, (time.monotonic() - t0) * 1000)
        return f"Baza danych niedostępna. ({exc})"

    if not rows:
        _append_rag_log(query, 0, 0.0, (time.monotonic() - t0) * 1000)
        return "Nie znalazłem nic pasującego w pamięci."

    # 3. Hybrid scoring & format
    lines: list[str] = [f'🔍 Recall: "{query}"', ""]
    for i, row in enumerate(rows, start=1):
        sem_score: float = float(row["sem_score"])
        days_ago: float = float(row["days_ago"]) if row["days_ago"] is not None else 0.0
        domain_w: float = float(row["domain_w"])

        recency_score = 1.0 / (1 + days_ago * 0.1)
        domain_w_norm = domain_w / 5.0
        importance = float(row.get("importance_score") or 0)
        hybrid = round(sem_score * 0.5 + recency_score * 0.15 + domain_w_norm * 0.15 + importance * 0.2, 4)

        title = row["title"] or "(bez tytułu)"
        domain = row["domain"] or ""
        url = row["url"] or ""
        fragment = (row["text"] or "")[:150].replace("\n", " ").strip()
        if len(row["text"] or "") > 150:
            fragment += "..."

        lines.append(f"{i}. [{hybrid:.2f}] {title} ({domain})")
        if fragment:
            lines.append(f"   Fragment: {fragment}")
        if url:
            lines.append(f"   🔗 {url}")
        lines.append("")

    latency_ms = (time.monotonic() - t0) * 1000
    top_score = float(rows[0]["sem_score"]) if rows else 0.0
    _append_rag_log(query, len(rows), top_score, latency_ms)

    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# Research — Google (browser-mcp) + LLM (Ollama) triangulation
# ---------------------------------------------------------------------------

_RESEARCH_MODEL: str = os.environ.get("RESEARCH_MODEL", "qwen3:1.7b")


def _brave_search(query: str, count: int = 5) -> list[dict]:
    """Search via Brave Search API. Returns list of {title, url, snippet}."""
    if not _BRAVE_API_KEY:
        return []
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": count},
                headers={"X-Subscription-Token": _BRAVE_API_KEY, "Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for item in data.get("web", {}).get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("description", ""),
                })
            return results
    except Exception as exc:
        print(f"[bridge] Brave search error: {exc}", flush=True)
        return []


def _llm_answer(question: str, context: str) -> tuple[str, dict]:
    """Call hermes-llm-proxy (medium tier) with Google context + memory. Sync, returns (text, llm_meta)."""
    # Inject memory context (persistent facts + recent sessions)
    memory_ctx = ""
    try:
        memory_ctx = mem.build_context(query=question, max_persistent=5, max_recent=2)
    except Exception as exc:
        print(f"[bridge] memory context error: {exc}", flush=True)

    parts = ["/no_think"]
    if memory_ctx:
        parts.append(f"Kontekst z pamięci użytkownika:\n{memory_ctx}\n")
    parts.append(
        f"Odpowiedz w 3-5 zdaniach na pytanie użytkownika. "
        f"Użyj poniższego kontekstu z Google jeśli jest pomocny.\n\n"
        f"Kontekst z Google:\n{context[:2000]}\n\n"
        f"Pytanie: {question}\n\n"
        f"Odpowiedź (po polsku, zwięźle):"
    )
    prompt = "\n".join(parts)
    result = llm_client.call_llm(prompt, tier="medium", skill="research")
    if result.get("error"):
        print(f"[bridge] llm_client error: {result['error']}", flush=True)
        return "", result
    return result.get("text", "").strip(), result


async def _handle_research_async(question: str) -> str:
    """
    Call browser_google_search via browser-mcp for web results,
    then Ollama for LLM synthesis, compare and return Telegram reply.
    """
    from mcp_client import MCPClient

    t0 = time.monotonic()
    google_results: list = []
    llm_answer: str = ""
    google_ok = True
    llm_ok = True

    # 1. Web search — Brave API (preferred) or browser-mcp Google (fallback)
    if _BRAVE_API_KEY:
        google_results = _brave_search(question, count=5)
        if not google_results:
            google_ok = False
    else:
        try:
            async with MCPClient() as mcp:
                try:
                    google_results = await mcp.call(
                        "browser_google_search",
                        {"query": question, "top_n": 5},
                    )
                    if isinstance(google_results, dict) and "error" in google_results:
                        print(f"[bridge] Google error: {google_results}", flush=True)
                        google_results = []
                        google_ok = False
                    elif not isinstance(google_results, list):
                        google_results = []
                        google_ok = False
                except Exception as exc:
                    print(f"[bridge] Google search failed: {exc}", flush=True)
                    google_results = []
                    google_ok = False
        except Exception as exc:
            print(f"[bridge] MCP connection failed: {exc}", flush=True)
            google_ok = False

    # 2. LLM answer via hermes-llm-proxy (medium tier) with Google context
    context = "\n".join(
        f"- {r.get('title', '')}: {r.get('snippet', '')}"
        for r in google_results[:5]
    ) if google_results else "(brak wyników Google)"
    llm_answer, llm_meta = _llm_answer(question, context)
    if not llm_answer:
        llm_ok = False

    # 3. Triangulation
    divergent = False
    if google_ok and llm_ok and google_results and llm_answer:
        google_text = " ".join(
            r.get("snippet", "") + " " + r.get("title", "")
            for r in google_results[:3]
        ).lower()
        llm_lower = llm_answer.lower()
        google_words = {w for w in google_text.split() if len(w) > 4}
        overlap = sum(1 for w in google_words if w in llm_lower)
        if google_words and (overlap / len(google_words)) < 0.15:
            divergent = True

    # 4. Format reply
    lines: list[str] = []

    if not llm_ok and not google_ok:
        lines.append(f"Nie udało się zbadać: \"{question}\"")
        lines.append("Google i LLM niedostępne.")
    else:
        lines.append(f"Pytanie: \"{question}\"")
        lines.append("")

        if llm_ok and llm_answer:
            preview = llm_answer[:400]
            if len(llm_answer) > 400:
                preview += "..."
            lines.append(preview)
        elif not llm_ok:
            lines.append("[LLM niedostępny]")

        if divergent:
            lines.append("")
            lines.append("-- rozbieżność Google vs LLM --")

        if google_ok and google_results:
            lines.append("")
            lines.append("Źródła:")
            for i, r in enumerate(google_results[:3], 1):
                title = r.get("title", "")[:60]
                url = r.get("url", "")
                lines.append(f"  {i}. {title}")
                if url:
                    lines.append(f"     {url}")
        elif not google_ok:
            lines.append("")
            lines.append("[Google niedostępny, odpowiedź tylko z LLM]")

    latency_ms = (time.monotonic() - t0) * 1000
    _append_research_log(question, google_results, llm_answer, divergent, latency_ms,
                         tier=llm_meta.get("tier", "medium"),
                         model_used=llm_meta.get("model", ""),
                         llm_latency_ms=llm_meta.get("latency_ms", 0))

    return "\n".join(lines).rstrip()


def _handle_research(question: str) -> str:
    """Sync wrapper for the async research handler."""
    return asyncio.run(_handle_research_async(question))


# ---------------------------------------------------------------------------
# Skill handler: test-mcp-server
# ---------------------------------------------------------------------------

# Map of MCP server aliases to URLs
_MCP_SERVERS: dict[str, str] = {
    "browser-mcp": "http://browser-mcp:8000/sse",
    "chrome-readonly-mcp": "http://chrome-readonly-mcp:8000/sse",
    "fs-vinhunter": "http://mcp-fs-vinhunter:8000/sse",
    "alumnium": "http://mcp-alumnium:8000/sse",
}

# Tools safe to call without args (or with minimal safe args)
_SAFE_TOOL_CALLS: dict[str, dict] = {
    "browser_list_tabs": {},
    "browser_google_search": {"query": "test", "top_n": 1},
    "readonly_list_tabs": {},
    "chrome_ro_list_tabs": {},
}

# Tools always skipped (too slow, needs args, or side effects)
_SKIP_TOOLS: set[str] = {
    "browser_ask_chatgpt",       # too slow
    "browser_navigate",          # needs tab_id
    "browser_open_tab",          # side effect
    "readonly_extract_text",     # needs tab_id
    "readonly_extract_metadata", # needs tab_id
    "readonly_query_selector",   # needs tab_id
    "chrome_ro_get_page_text",   # needs tab_id
    "chrome_ro_get_page_meta",   # needs tab_id
    "chrome_ro_extract_selector", # needs tab_id
}


async def _handle_test_mcp_async(server_alias: str) -> str:
    """Connect to MCP server, list tools, exercise safe ones, return report."""
    from mcp_client import MCPClient

    url = _MCP_SERVERS.get(server_alias)
    if not url:
        known = ", ".join(sorted(_MCP_SERVERS))
        return f"Nieznany serwer '{server_alias}'. Dostępne: {known}"

    t0 = time.monotonic()
    results: list[str] = []
    ok_count = 0
    err_count = 0
    skip_count = 0

    try:
        async with MCPClient(url) as mcp:
            # List tools
            tools_resp = await mcp._session.list_tools()
            tool_names = [t.name for t in tools_resp.tools]
            results.append(f"MCP Test: {server_alias} ({url})")
            results.append(f"Tools found: {len(tool_names)}")
            results.append("")

            for tname in tool_names:
                if tname in _SKIP_TOOLS:
                    results.append(f"  ⏭ {tname} — skipped")
                    skip_count += 1
                    continue

                args = _SAFE_TOOL_CALLS.get(tname)
                if args is None:
                    results.append(f"  ⏭ {tname} — skipped (unknown)")
                    skip_count += 1
                    continue

                tc0 = time.monotonic()
                try:
                    resp = await mcp.call(tname, args)
                    lat = int((time.monotonic() - tc0) * 1000)
                    preview = str(resp)[:80]
                    results.append(f"  ✅ {tname} — ok ({lat}ms) — {preview}")
                    ok_count += 1
                except Exception as exc:
                    lat = int((time.monotonic() - tc0) * 1000)
                    results.append(f"  ❌ {tname} — error ({lat}ms) — {exc}")
                    err_count += 1

    except Exception as exc:
        return f"MCP Test: {server_alias} — FAILED\nConnection error: {exc}"

    total_s = time.monotonic() - t0
    results.append("")
    tested = ok_count + err_count
    results.append(f"Summary: {tested}/{len(tool_names)} tested, {ok_count} ok, {err_count} errors, {skip_count} skipped")
    results.append(f"Total: {total_s:.1f}s")
    return "\n".join(results)


def _handle_test_mcp(server_alias: str) -> str:
    """Sync wrapper for test-mcp-server."""
    return asyncio.run(_handle_test_mcp_async(server_alias))


# ---------------------------------------------------------------------------
# Skill handler: test-rag-endpoint
# ---------------------------------------------------------------------------

_RAG_API_URL: str = os.environ.get("RAG_API_URL", "http://host.docker.internal:8000")


def _handle_test_rag() -> str:
    """Test RAG API: health, documents list, chat query."""
    t0 = time.monotonic()
    results: list[str] = [f"RAG API Test ({_RAG_API_URL})"]
    ok_count = 0
    err_count = 0

    checks = [
        ("GET /api/v1/health", "get", "/api/v1/health", None),
        ("GET /api/v1/documents", "get", "/api/v1/documents?limit=3", None),
        ("GET /api/v1/stats", "get", "/api/v1/stats", None),
    ]

    with httpx.Client(timeout=30.0) as client:
        for label, method, path, body in checks:
            tc0 = time.monotonic()
            try:
                if method == "get":
                    resp = client.get(f"{_RAG_API_URL}{path}")
                else:
                    resp = client.post(f"{_RAG_API_URL}{path}", json=body)
                lat = int((time.monotonic() - tc0) * 1000)
                preview = resp.text[:100]
                if resp.status_code < 400:
                    results.append(f"  ✅ {label} — {resp.status_code} ({lat}ms) — {preview}")
                    ok_count += 1
                else:
                    results.append(f"  ⚠️ {label} — {resp.status_code} ({lat}ms) — {preview}")
                    err_count += 1
            except Exception as exc:
                lat = int((time.monotonic() - tc0) * 1000)
                results.append(f"  ❌ {label} — error ({lat}ms) — {exc}")
                err_count += 1

    total_s = time.monotonic() - t0
    total = ok_count + err_count
    results.append("")
    results.append(f"Summary: {ok_count}/{total} ok, {err_count} errors. Total: {total_s:.1f}s")
    return "\n".join(results)


# ---------------------------------------------------------------------------
# Skill handler: test-trading / test-selfmadeagent (HTTP health check)
# ---------------------------------------------------------------------------

_SERVICE_URLS: dict[str, tuple[str, str]] = {
    "test-trading": (
        os.environ.get("TRADING_APP_URL", "http://host.docker.internal:8501"),
        "Trading App (Streamlit)",
    ),
    "test-selfmadeagent": (
        os.environ.get("SELFMADEAGENT_URL", "http://host.docker.internal:8080"),
        "Selfmadeagent (Orchestrator)",
    ),
}


def _handle_service_health(skill_name: str) -> str:
    """Simple HTTP health check for trading-app or selfmadeagent."""
    url, label = _SERVICE_URLS[skill_name]
    t0 = time.monotonic()

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url)
        lat = int((time.monotonic() - t0) * 1000)
        return f"{label} ({url})\n  ✅ HTTP {resp.status_code} ({lat}ms)\n  Response: {resp.text[:150]}"
    except httpx.ConnectError:
        return f"{label} ({url})\n  ❌ Connection refused — container not running"
    except httpx.ConnectTimeout:
        return f"{label} ({url})\n  ❌ Connection timeout — container not responding"
    except Exception as exc:
        lat = int((time.monotonic() - t0) * 1000)
        return f"{label} ({url})\n  ❌ Error ({lat}ms): {exc}"


# ---------------------------------------------------------------------------
# Skill handler: scan-rss-opportunities
# ---------------------------------------------------------------------------

_USER_SKILLS = "Python, RAG, automation, LLM, scraping, Docker, n8n, AI agents"

_SCAN_QUERIES = [
    "site:reddit.com/r/forhire python OR automation OR LLM",
    "site:useme.eu python OR automatyzacja OR scraping",
    "freelance python RAG automation remote 2026",
]


async def _handle_scan_rss_async() -> str:
    """Search job boards via Google, score matches with Ollama."""
    from mcp_client import MCPClient

    t0 = time.monotonic()
    all_results: list[dict] = []
    seen_urls: set[str] = set()

    if _BRAVE_API_KEY:
        for q in _SCAN_QUERIES:
            results = _brave_search(q, count=5)
            for r in results:
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append(r)
    else:
        try:
            async with MCPClient() as mcp:
                for q in _SCAN_QUERIES:
                    try:
                        results = await mcp.call("browser_google_search", {"query": q, "top_n": 5})
                        if isinstance(results, list):
                            for r in results:
                                url = r.get("url", "")
                                if url and url not in seen_urls:
                                    seen_urls.add(url)
                                    all_results.append(r)
                    except Exception as exc:
                        print(f"[bridge] scan-rss query error: {exc}", flush=True)
        except Exception as exc:
            return f"Scan RSS — FAILED\nMCP error: {exc}"

    if not all_results:
        return "Scan RSS — brak wyników z Google."

    # Score with Ollama
    scored: list[tuple[int, dict]] = []
    for r in all_results[:15]:  # max 15 to score
        title = r.get("title", "")
        snippet = r.get("snippet", "")
        score = _score_opportunity(title, snippet)
        if score >= 5:
            scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)

    lines = [f"Scan RSS — {len(all_results)} znalezionych, {len(scored)} pasujących"]
    lines.append("")
    if not scored:
        lines.append("Brak ofert pasujących do profilu (score >= 5).")
    else:
        for i, (score, r) in enumerate(scored[:8], 1):
            title = r.get("title", "")[:60]
            url = r.get("url", "")
            snippet = r.get("snippet", "")[:80]
            lines.append(f"{i}. [{score}/10] {title}")
            if url:
                lines.append(f"   {url}")
            if snippet:
                lines.append(f"   {snippet}")
            lines.append("")

    total_s = time.monotonic() - t0
    lines.append(f"Total: {total_s:.1f}s")
    return "\n".join(lines)


def _score_opportunity(title: str, snippet: str) -> int:
    """Quick keyword scoring (no LLM, fast). Returns 0-10."""
    text = (title + " " + snippet).lower()
    keywords = {
        "python": 3, "rag": 3, "llm": 3, "automation": 2, "scraping": 2,
        "docker": 2, "n8n": 2, "ai": 1, "bot": 1, "api": 1,
        "machine learning": 2, "nlp": 2, "fastapi": 2, "langchain": 2,
    }
    score = sum(v for k, v in keywords.items() if k in text)
    return min(score, 10)


def _handle_scan_rss() -> str:
    """Sync wrapper for scan-rss."""
    return asyncio.run(_handle_scan_rss_async())


# ---------------------------------------------------------------------------
# Skill handler: crypto-arbitrage-watch
# ---------------------------------------------------------------------------

_ARBIT_THRESHOLD: float = float(os.environ.get("ARBIT_THRESHOLD", "0.5"))
_ARBIT_PAIRS = ["BTC_USDT", "ETH_USDT", "SOL_USDT"]


def _handle_crypto_arbitrage() -> str:
    """Compare prices between Gate.io and Binance for key pairs."""
    t0 = time.monotonic()
    lines = ["Crypto Arbitrage Scan (Gate.io vs Binance)", ""]
    alerts = 0

    with httpx.Client(timeout=15.0) as client:
        # Gate.io tickers
        gate_prices: dict[str, float] = {}
        try:
            resp = client.get("https://api.gateio.ws/api/v4/spot/tickers")
            resp.raise_for_status()
            for t in resp.json():
                pair = t.get("currency_pair", "")
                last = t.get("last", "0")
                gate_prices[pair] = float(last)
        except Exception as exc:
            return f"Crypto Arbitrage — Gate.io error: {exc}"

        # Binance tickers
        binance_prices: dict[str, float] = {}
        try:
            resp = client.get("https://api.binance.com/api/v3/ticker/price")
            resp.raise_for_status()
            for t in resp.json():
                symbol = t.get("symbol", "")
                price = float(t.get("price", "0"))
                binance_prices[symbol] = price
        except Exception as exc:
            return f"Crypto Arbitrage — Binance error: {exc}"

    for pair in _ARBIT_PAIRS:
        # Gate.io format: BTC_USDT, Binance format: BTCUSDT
        gate_key = pair
        binance_key = pair.replace("_", "")

        gp = gate_prices.get(gate_key, 0)
        bp = binance_prices.get(binance_key, 0)

        if gp <= 0 or bp <= 0:
            lines.append(f"  {pair}: data missing (gate={gp}, binance={bp})")
            continue

        spread = abs(gp - bp) / min(gp, bp) * 100
        flag = ""
        if spread >= _ARBIT_THRESHOLD:
            flag = " ⚠️ alert"
            alerts += 1
        elif spread >= 2.0:
            flag = " ⛔ suspicious"

        direction = "Gate→Binance" if gp < bp else "Binance→Gate"
        base = pair.split("_")[0]
        lines.append(
            f"  {base}/USDT: Gate ${gp:,.2f} | Binance ${bp:,.2f} | "
            f"spread: {spread:.2f}%{flag}"
        )
        if flag:
            lines.append(f"    Buy: {direction.split('→')[0]}, Sell: {direction.split('→')[1]}")

    total_s = time.monotonic() - t0
    lines.append("")
    lines.append(f"Summary: {alerts}/{len(_ARBIT_PAIRS)} above threshold ({_ARBIT_THRESHOLD}%). Total: {total_s:.1f}s")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Skill handler: domain-flip-radar
# ---------------------------------------------------------------------------

_DOMAIN_QUERIES = [
    "expired domains AI automation 2026",
    "cheap domains artificial intelligence",
    "domain auction LLM chatbot",
]


async def _handle_domain_flip_async() -> str:
    """Search for expiring AI/automation domains."""
    from mcp_client import MCPClient

    t0 = time.monotonic()
    all_results: list[dict] = []
    seen_urls: set[str] = set()

    if _BRAVE_API_KEY:
        for q in _DOMAIN_QUERIES:
            results = _brave_search(q, count=5)
            for r in results:
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append(r)
    else:
        try:
            async with MCPClient() as mcp:
                for q in _DOMAIN_QUERIES:
                    try:
                        results = await mcp.call("browser_google_search", {"query": q, "top_n": 5})
                        if isinstance(results, list):
                            for r in results:
                                url = r.get("url", "")
                                if url and url not in seen_urls:
                                    seen_urls.add(url)
                                    all_results.append(r)
                    except Exception as exc:
                        print(f"[bridge] domain-flip query error: {exc}", flush=True)
        except Exception as exc:
            return f"Domain Flip Radar — FAILED\nMCP error: {exc}"

    lines = [f"Domain Flip Radar (AI/Automation)", f"Results: {len(all_results)}", ""]
    if not all_results:
        lines.append("Brak wyników.")
    else:
        for i, r in enumerate(all_results[:10], 1):
            title = r.get("title", "")[:60]
            url = r.get("url", "")
            snippet = r.get("snippet", "")[:80]
            lines.append(f"{i}. {title}")
            if url:
                lines.append(f"   {url}")
            if snippet:
                lines.append(f"   {snippet}")
            lines.append("")

    total_s = time.monotonic() - t0
    lines.append(f"Total: {total_s:.1f}s")
    return "\n".join(lines)


def _handle_domain_flip() -> str:
    """Sync wrapper for domain-flip."""
    return asyncio.run(_handle_domain_flip_async())


# ---------------------------------------------------------------------------
# Skill handler: client-followup
# ---------------------------------------------------------------------------

_CLIENTS_FILE = Path(os.environ.get("HERMES_AUDIT_DIR", "/audit")) / "clients.json"


def _handle_client_followup() -> str:
    """Check clients.json for follow-up reminders."""
    if not _CLIENTS_FILE.exists():
        return (
            "Client Followup — brak listy klientów.\n"
            "Stwórz /audit/clients.json z formatem:\n"
            '[{"name": "Jan", "email": "jan@example.com", '
            '"last_contact": "2026-03-01", "project": "RAG pipeline"}]'
        )

    try:
        clients = json.loads(_CLIENTS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"Client Followup — błąd odczytu clients.json: {exc}"

    if not clients:
        return "Client Followup — lista klientów jest pusta."

    now = datetime.now(timezone.utc)
    due: list[dict] = []
    for c in clients:
        last = c.get("last_contact", "")
        if not last:
            continue
        try:
            last_dt = datetime.fromisoformat(last).replace(tzinfo=timezone.utc)
            days_ago = (now - last_dt).days
            if days_ago >= 30:
                c["_days_ago"] = days_ago
                due.append(c)
        except ValueError:
            continue

    if not due:
        return f"Client Followup — żaden z {len(clients)} klientów nie wymaga follow-up (< 30 dni)."

    lines = [f"Client Followup ({len(due)} due)", ""]
    for i, c in enumerate(due[:10], 1):
        name = c.get("name", "?")
        email = c.get("email", "brak email")
        project = c.get("project", "?")
        days = c.get("_days_ago", 0)
        lines.append(f"{i}. {name} ({email})")
        lines.append(f"   Last contact: {days} days ago (project: {project})")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Skill handler: auto-todo-extract
# ---------------------------------------------------------------------------

def _handle_auto_todo() -> str:
    """Read recent tabs from hermes_tabs, send to Ollama to extract TODOs."""
    t0 = time.monotonic()

    # 1. Fetch recent tabs with content (last 24h, max 5)
    try:
        conn = _get_db_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT t.title, t.domain, t.raw_text "
                "FROM hermes_tabs t "
                "WHERE t.captured_at > now() - interval '24 hours' "
                "AND t.raw_text IS NOT NULL AND length(t.raw_text) > 100 "
                "ORDER BY t.captured_at DESC LIMIT 5"
            )
            tabs = cur.fetchall()
    except Exception as exc:
        return f"Auto-TODO — DB error: {exc}"

    if not tabs:
        return "Auto-TODO — brak nowych tabów z ostatnich 24h."

    # 2. Build content summary for Ollama (truncate each tab to 400 chars)
    tab_summaries = []
    for title, domain, raw_text in tabs:
        snippet = (raw_text or "")[:400].replace("\n", " ").strip()
        tab_summaries.append(f"[{domain}] {title}: {snippet}")

    combined = "\n".join(tab_summaries)

    # 3. Ask llm-proxy (easy tier) to extract TODOs
    prompt = (
        "/no_think\n"
        "Z poniższych zakładek wyciągnij TODO (do zrobienia/sprawdzenia/kupienia). "
        "Ignoruj reklamy. Format: - [ ] TODO (domena)\n"
        "Jeśli brak: \"Brak TODO.\"\n\n"
        f"{combined[:1500]}\n\n"
        "TODO:"
    )

    result = llm_client.call_llm(prompt, tier="easy", skill="auto-todo")
    if result.get("error"):
        return f"Auto-TODO — LLM error: {result['error']}"
    todos = result.get("text", "").strip()

    if not todos:
        return "Auto-TODO — LLM nie zwrócił wyników."

    latency_ms = int((time.monotonic() - t0) * 1000)
    lines = [
        f"Auto-TODO ({len(tabs)} tabów, {latency_ms}ms, tier=easy, model={result.get('model', '')})",
        "",
        todos[:1500],
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Skill handler: classify-tabs
# ---------------------------------------------------------------------------

_TAB_CATEGORIES = ["tech", "shopping", "news", "social", "work", "learning", "entertainment", "finance", "other"]

# Rule-based classification — fast, no LLM needed
_DOMAIN_CATEGORY: dict[str, str] = {
    "github.com": "tech", "stackoverflow.com": "tech", "gitlab.com": "tech",
    "dev.to": "tech", "medium.com": "tech", "hackernews.com": "tech",
    "news.ycombinator.com": "tech", "arxiv.org": "learning",
    "allegro.pl": "shopping", "amazon.com": "shopping", "ceneo.pl": "shopping",
    "ebay.com": "shopping", "aliexpress.com": "shopping", "pepper.pl": "shopping",
    "mediaexpert.pl": "shopping", "morele.net": "shopping", "x-kom.pl": "shopping",
    "olx.pl": "shopping", "empik.com": "shopping",
    "reddit.com": "social", "twitter.com": "social", "x.com": "social",
    "facebook.com": "social", "linkedin.com": "social", "instagram.com": "social",
    "youtube.com": "entertainment", "netflix.com": "entertainment",
    "twitch.tv": "entertainment", "spotify.com": "entertainment",
    "chatgpt.com": "tech", "claude.ai": "tech", "gemini.google.com": "tech",
    "docs.google.com": "work", "notion.so": "work", "trello.com": "work",
    "linear.app": "work", "jira.atlassian.com": "work",
    "udemy.com": "learning", "coursera.org": "learning",
    "wikipedia.org": "learning", "w3schools.com": "learning",
    "bankier.pl": "finance", "investing.com": "finance",
    "tradingview.com": "finance", "coinmarketcap.com": "finance",
    "gate.io": "finance", "binance.com": "finance",
    "onet.pl": "news", "wp.pl": "news", "gazeta.pl": "news",
    "tvn24.pl": "news", "bbc.com": "news", "cnn.com": "news",
}

_TITLE_KEYWORDS: dict[str, list[str]] = {
    "tech": ["api", "docker", "python", "javascript", "react", "node", "linux",
             "git", "deploy", "server", "database", "llm", "ai", "ml", "code",
             "programming", "developer", "software", "debug", "framework"],
    "shopping": ["kup", "cena", "sklep", "oferta", "zł", "pln", "koszyk",
                 "zamów", "produkt", "opinie", "allegro", "buy", "price", "shop"],
    "finance": ["bitcoin", "crypto", "btc", "eth", "trading", "giełda",
                "inwestycj", "kurs", "walut", "bank"],
    "learning": ["tutorial", "course", "learn", "guide", "how to", "documentation",
                 "docs", "kurs", "nauka", "poradnik"],
    "news": ["news", "breaking", "wiadomo", "aktualn"],
}


def _classify_single(title: str, domain: str, snippet: str) -> str:
    """Classify a tab using domain rules + title keywords. Fast, no LLM."""
    # 1. Exact domain match
    if domain in _DOMAIN_CATEGORY:
        return _DOMAIN_CATEGORY[domain]
    # Check parent domain (e.g., sub.github.com → github.com)
    for known_domain, cat in _DOMAIN_CATEGORY.items():
        if domain.endswith("." + known_domain):
            return cat

    # 2. Title keyword scoring
    title_lower = (title + " " + snippet[:200]).lower()
    scores: dict[str, int] = {}
    for cat, keywords in _TITLE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in title_lower)
        if score > 0:
            scores[cat] = score

    if scores:
        return max(scores, key=scores.get)

    return "other"


def _handle_classify_tabs() -> str:
    """Classify uncategorized tabs in hermes_tabs."""
    t0 = time.monotonic()

    # Need a writable connection for UPDATE
    try:
        import psycopg2 as pg2
        write_conn = pg2.connect(_RECALL_DSN)
        write_conn.autocommit = True
    except Exception as exc:
        return f"Classify — DB error: {exc}"

    try:
        with write_conn.cursor() as cur:
            cur.execute(
                "SELECT id, title, domain, "
                "COALESCE(LEFT(raw_text, 500), '') as snippet "
                "FROM hermes_tabs "
                "WHERE category IS NULL "
                "ORDER BY captured_at DESC LIMIT 20"
            )
            tabs = cur.fetchall()
    except Exception as exc:
        write_conn.close()
        return f"Classify — query error: {exc}"

    if not tabs:
        write_conn.close()
        return "Classify — wszystkie taby mają kategorie."

    classified = 0
    results: list[str] = [f"Classifying {len(tabs)} tabs...", ""]

    for tab_id, title, domain, snippet in tabs:
        cat = _classify_single(title or "", domain or "", snippet)
        try:
            with write_conn.cursor() as cur:
                cur.execute(
                    "UPDATE hermes_tabs SET category = %s WHERE id = %s",
                    (cat, tab_id),
                )
            classified += 1
            results.append(f"  [{cat:13}] {(title or '?')[:50]}")
        except Exception as exc:
            results.append(f"  [ERROR] {tab_id}: {exc}")

    write_conn.close()
    latency_ms = int((time.monotonic() - t0) * 1000)
    results.append("")
    results.append(f"Classified: {classified}/{len(tabs)} ({latency_ms}ms)")
    return "\n".join(results)


# ---------------------------------------------------------------------------
# Tabs handler
# ---------------------------------------------------------------------------

def _handle_tabs(arg: str) -> str:
    """Show recently indexed tabs from hermes_tabs or search by keyword."""
    try:
        conn = _get_db_conn()
        cur = conn.cursor()

        if arg:
            # Search by keyword in title/url/domain
            cur.execute(
                "SELECT url, title, domain, captured_at, "
                "(SELECT COUNT(*) FROM hermes_tab_chunks c WHERE c.tab_id = t.id) AS chunks, "
                "category, importance_score "
                "FROM hermes_tabs t "
                "WHERE title ILIKE %s OR url ILIKE %s OR domain ILIKE %s "
                "ORDER BY importance_score DESC NULLS LAST, captured_at DESC LIMIT 15",
                (f"%{arg}%", f"%{arg}%", f"%{arg}%"),
            )
        else:
            cur.execute(
                "SELECT url, title, domain, captured_at, "
                "(SELECT COUNT(*) FROM hermes_tab_chunks c WHERE c.tab_id = t.id) AS chunks, "
                "category, importance_score "
                "FROM hermes_tabs t "
                "ORDER BY importance_score DESC NULLS LAST, captured_at DESC LIMIT 15",
            )

        rows = cur.fetchall()
        total_cur = conn.cursor()
        total_cur.execute("SELECT COUNT(*) FROM hermes_tabs")
        total = total_cur.fetchone()[0]
        total_cur.execute("SELECT COUNT(*) FROM hermes_tab_chunks")
        total_chunks = total_cur.fetchone()[0]

        if not rows:
            if arg:
                return f"Brak tabów pasujących do \"{arg}\". Łącznie: {total} tabów, {total_chunks} chunków."
            return f"Brak zaindeksowanych tabów. Łącznie: {total}."

        header = f"Taby ({len(rows)}/{total}, {total_chunks} chunków)"
        if arg:
            header = f"Taby \"{arg}\" ({len(rows)} z {total})"

        lines = [header, ""]
        for row in rows:
            url, title, domain, last_seen, chunks = row[0], row[1], row[2], row[3], row[4]
            cat = row[5] if len(row) > 5 else None
            importance = row[6] if len(row) > 6 else None
            t = title[:50] if title else "(brak tytułu)"
            d = last_seen.strftime("%m-%d %H:%M") if last_seen else "?"
            cat_tag = f" [{cat}]" if cat else ""
            score_tag = f" [{float(importance):.2f}]" if importance is not None else ""
            lines.append(f"  [{d}]{cat_tag}{score_tag} {t}")
            lines.append(f"    {domain} | {chunks} ch | {url[:70]}")
            lines.append("")

        return "\n".join(lines)

    except Exception as exc:
        return f"Tabs error: {exc}"


# ---------------------------------------------------------------------------
# Memory handlers
# ---------------------------------------------------------------------------

def _handle_remember(fact: str) -> str:
    """Save a persistent fact."""
    if not fact:
        return "Usage: /remember <fakt do zapamiętania>"
    row_id = mem.remember(fact)
    total = mem.persistent_count()
    return f"Zapamiętane (#{row_id}): {fact}\nŁącznie faktów: {total}"


def _handle_forget(query: str) -> str:
    """Delete persistent facts matching query."""
    if not query:
        return "Usage: /forget <szukana fraza>"
    count = mem.forget(query)
    if count == 0:
        return f"Nie znaleziono faktów pasujących do: \"{query}\""
    return f"Usunięto {count} fakt(ów) pasujących do: \"{query}\""


def _handle_history(arg: str) -> str:
    """Show recent interactions or search history."""
    # If arg is a number, show that many recent items
    # If arg is text, search for it
    # If empty, show last 5
    if not arg:
        sessions = mem.recent_sessions(limit=5)
        return _format_history(sessions, "Ostatnie 5 interakcji")

    if arg.isdigit():
        n = min(int(arg), 20)
        sessions = mem.recent_sessions(limit=n)
        return _format_history(sessions, f"Ostatnie {n} interakcji")

    # Text search
    sessions = mem.search_sessions(arg, limit=5)
    return _format_history(sessions, f"Wyniki dla: \"{arg}\"")


def _format_history(sessions: list[dict], title: str) -> str:
    """Format session list for Telegram."""
    total = mem.session_count()
    lines = [f"{title} (total: {total})", ""]

    if not sessions:
        lines.append("Brak wyników.")
        return "\n".join(lines)

    for s in sessions:
        date = s["ts"][:10]
        skill = s.get("skill_name", "")
        skill_tag = f" [{skill}]" if skill else ""
        msg = s["user_message"][:60]
        reply = s["reply"][:80]
        lat = s.get("latency_ms", 0)
        lines.append(f"  [{date}]{skill_tag} Q: {msg}")
        lines.append(f"  → {reply}")
        if lat:
            lines.append(f"  ({lat}ms)")
        lines.append("")

    # Persistent facts summary
    facts_count = mem.persistent_count()
    if facts_count:
        lines.append(f"Zapamiętane fakty: {facts_count}")
        facts = mem.get_all_persistent(limit=5)
        for f in facts:
            lines.append(f"  - {f['fact']}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cron scheduler
# ---------------------------------------------------------------------------

def _cron_log() -> Path:
    return _AUDIT_DIR / "cron.log"


def _append_cron_log(skill_name: str, success: bool, latency_ms: int, preview: str) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "skill": skill_name,
        "success": success,
        "latency_ms": latency_ms,
        "preview": preview[:200],
    }
    with _cron_log().open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _pool_bucket_ts(now: datetime) -> datetime:
    """Floor timestamp to the nearest 30-minute bucket."""
    minute_bucket = 30 if now.minute >= 30 else 0
    return now.replace(minute=minute_bucket, second=0, microsecond=0)


def _pool_is_open(ts: datetime) -> bool:
    """Return True if the pool is open at the given Warsaw-timezone timestamp.

    Reads open/close hours from /config/pool_hours.csv (weekday 0=Mon … 6=Sun).
    Falls back to 6–22 every day if the file is missing or unreadable.
    """
    hours_path = Path("/config/pool_hours.csv")
    try:
        with hours_path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if int(row["weekday"]) == ts.weekday():
                    return int(row["open"]) <= ts.hour < int(row["close"])
    except Exception:
        pass
    return 6 <= ts.hour < 22


def _handle_pool_monitor() -> str:
    """Fetch pool occupancy from cr.nieporet.pl, write to CSV + Postgres."""
    from bs4 import BeautifulSoup

    global _LAST_POOL_MONITOR

    URL = "https://cr.nieporet.pl/"
    HEADERS = {"User-Agent": "HermesPoolMonitor/1.0"}

    tz = ZoneInfo("Europe/Warsaw")
    ts = _pool_bucket_ts(datetime.now(tz=tz))

    if not _pool_is_open(ts):
        return f"Basen zamknięty ({ts.strftime('%H:%M')}) — brak sprawdzenia"

    # HTTP fetch — exponential backoff for network/5xx only
    resp = None
    error_text: str | None = None
    t0 = time.monotonic()

    for delay in [0, 1, 3]:
        if delay:
            time.sleep(delay)
        try:
            resp = httpx.get(URL, timeout=10, headers=HEADERS)
            resp.raise_for_status()
            break
        except (httpx.NetworkError, httpx.TimeoutException) as exc:
            error_text = str(exc)
            resp = None
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                error_text = str(exc)
                resp = None
            else:
                error_text = str(exc)
                break

    scrape_ms = int((time.monotonic() - t0) * 1000)

    # Parse
    people_count: int | None = None
    scrape_ok = False

    if resp is not None:
        try:
            soup = BeautifulSoup(resp.text, "lxml")
            span = soup.select_one("div.attendance div.num span")
            if span and span.text.strip().isdigit():
                people_count = int(span.text.strip())
                scrape_ok = True
            else:
                error_text = f"selector miss: {span!r}"
                snapshot = _AUDIT_DIR / f"pool_parse_error_{ts.strftime('%Y%m%d_%H%M')}.html"
                snapshot.write_text(resp.text, encoding="utf-8")
        except Exception as exc:
            error_text = f"parse: {exc}"
            if resp is not None:
                snapshot = _AUDIT_DIR / f"pool_parse_error_{ts.strftime('%Y%m%d_%H%M')}.html"
                snapshot.write_text(resp.text, encoding="utf-8")

    # CSV (monthly rotation)
    csv_path = _AUDIT_DIR / f"pool-{ts.strftime('%Y-%m')}.csv"
    write_header = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["recorded_at", "people_count", "scrape_ok", "scrape_ms", "error"])
        writer.writerow([
            ts.isoformat(),
            people_count if people_count is not None else "",
            "true" if scrape_ok else "false",
            scrape_ms,
            error_text or "",
        ])

    # Postgres
    try:
        conn = psycopg2.connect(_RECALL_DSN)
        conn.autocommit = True
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO hermes_pool_occupancy
                    (recorded_at, people_count, scrape_ok, scrape_ms, error)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (ts, people_count, scrape_ok, scrape_ms, error_text),
            )
        finally:
            conn.close()
    except Exception as exc:
        print(f"[pool-monitor] postgres error: {exc}", flush=True)

    # Health state
    _LAST_POOL_MONITOR = {"ok": scrape_ok, "last_run": ts.isoformat(), "count": people_count}

    if scrape_ok:
        return f"Basen: {people_count} osób ({ts.strftime('%H:%M')})"
    return f"Basen: błąd scrape ({scrape_ms}ms) — {error_text}"


# ---------------------------------------------------------------------------
# Skill handler: scrape-autocentrum
# ---------------------------------------------------------------------------

def _autocentrum_load_queue() -> list[dict]:
    """Load scrape queue from JSON file, initialize from seed if missing."""
    if _AUTOCENTRUM_QUEUE_FILE.exists():
        try:
            return json.loads(_AUTOCENTRUM_QUEUE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    queue = [dict(item) for item in _AUTOCENTRUM_SEED]
    _AUTOCENTRUM_QUEUE_FILE.write_text(
        json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return queue


def _autocentrum_save_queue(queue: list[dict]) -> None:
    _AUTOCENTRUM_QUEUE_FILE.write_text(
        json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _autocentrum_embed(text: str) -> list[float] | None:
    """Embed text via Ollama qwen3-embedding:0.6b. Returns None on error."""
    try:
        resp = httpx.post(
            f"{_OLLAMA_URL}/api/embed",
            json={"model": _EMBEDDING_MODEL, "input": text},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings = data.get("embeddings") or data.get("embedding")
        if embeddings:
            return embeddings[0] if isinstance(embeddings[0], list) else embeddings
        return None
    except Exception as exc:
        print(f"[scrape-autocentrum] embed error: {exc}", flush=True)
        return None


def _handle_scrape_autocentrum(args: str = "") -> str:
    """
    Scrape autocentrum.pl for one car model.
    args: "BMW Seria3" for manual trigger, "" for cron (picks next from queue).
    """
    import re as _re

    # Determine which model to scrape
    queue = _autocentrum_load_queue()
    make: str = ""
    model: str = ""

    if args.strip():
        parts = args.strip().split(None, 1)
        make = parts[0] if parts else ""
        model = parts[1] if len(parts) > 1 else ""
    else:
        pending = [item for item in queue if not item.get("done")]
        if not pending:
            for item in queue:
                item["done"] = False
            _autocentrum_save_queue(queue)
            pending = queue
        make = pending[0]["make"]
        model = pending[0]["model"]

    if not make or not model:
        return "⚠️ autocentrum: brakuje make/model. Użyj: /skill scrape-autocentrum BMW Seria3"

    # 1. Find autocentrum.pl URL via Brave Search
    search_query = f"site:autocentrum.pl {make} {model} test opinia"
    search_results = _brave_search(search_query, count=3)

    model_url: str | None = None
    make_slug = make.lower().replace("-", "").replace(" ", "")
    for r in search_results:
        url = r.get("url", "")
        if "autocentrum.pl" in url and make_slug in url.lower().replace("-", "").replace(" ", ""):
            model_url = url
            break

    if not model_url and search_results:
        # Use first result with autocentrum.pl regardless
        for r in search_results:
            if "autocentrum.pl" in r.get("url", ""):
                model_url = r.get("url")
                break

    if not model_url:
        return f"⚠️ autocentrum: nie znaleziono strony dla {make} {model} (Brave Search: 0 trafień)"

    # 2. Connect to DB — try hermes_ingest first, fall back to rag user
    conn = None
    cur = None
    _ingest_pw = os.environ.get("HERMES_INGEST_PASSWORD", "")
    _ingest_dsn = _RECALL_DSN.replace(
        "rag:ragpass@", f"hermes_ingest:{_ingest_pw}@"
    ) if _ingest_pw else None
    try:
        if _ingest_dsn:
            conn = psycopg2.connect(_ingest_dsn)
        else:
            raise Exception("no ingest creds")
    except Exception:
        try:
            conn = psycopg2.connect(_RECALL_DSN)
        except Exception as exc2:
            return f"⚠️ autocentrum: błąd połączenia DB: {exc2}"
    conn.autocommit = True
    cur = conn.cursor()

    try:
        # 3. Insert model record
        cur.execute(
            """
            INSERT INTO autocentrum_models (make, model, url)
            VALUES (%s, %s, %s)
            ON CONFLICT (url) DO NOTHING
            """,
            (make, model, model_url),
        )
        cur.execute("SELECT id FROM autocentrum_models WHERE url = %s", (model_url,))
        row = cur.fetchone()
        if not row:
            return f"⚠️ autocentrum: nie można ustalić model_id dla {model_url}"
        model_id = row[0]

        # 4. Scrape page text via browser-mcp (async, run in thread)
        editorial_count = 0

        async def _scrape_async() -> tuple[int, int]:
            from mcp_client import MCPClient
            ed_count = 0
            op_count = 0
            try:
                async with MCPClient("http://browser-mcp:8000/sse") as mcp:
                    result = await mcp.call("browser_navigate", {"url": model_url})
                    page_text = ""
                    if isinstance(result, dict):
                        page_text = result.get("text", result.get("content", ""))
                    elif isinstance(result, str):
                        page_text = result

                    if not page_text or len(page_text) < 100:
                        return ed_count, op_count

                    # Extract rating
                    rating: float | None = None
                    m = _re.search(r"(\d+(?:[.,]\d+)?)\s*/\s*10", page_text)
                    if m:
                        try:
                            rating = float(m.group(1).replace(",", "."))
                        except ValueError:
                            pass

                    # Chunk + embed + insert (max 4000 chars = up to 5 chunks)
                    chunk_size = 800
                    editorial_title = f"{make} {model} — test autocentrum.pl"
                    for i in range(0, min(len(page_text), 4000), chunk_size):
                        chunk = page_text[i: i + chunk_size]
                        if len(chunk) < 50:
                            continue
                        embedding = _autocentrum_embed(chunk)
                        emb_str = (
                            f"[{','.join(str(x) for x in embedding)}]"
                            if embedding else None
                        )
                        cur.execute(
                            """
                            INSERT INTO autocentrum_reviews
                                (model_id, source, title, content, rating, url, embedding)
                            VALUES (%s, 'editorial', %s, %s, %s, %s, %s)
                            """,
                            (
                                model_id,
                                editorial_title if i == 0 else None,
                                chunk,
                                rating,
                                model_url if i == 0 else None,
                                emb_str,
                            ),
                        )
                        ed_count += 1

                    # Owner opinions — navigate to opinions URL
                    import time as _time
                    opinions_url: str | None = None
                    # Look for opinions link in page text
                    op_match = _re.search(
                        r'(https?://[^\s"\']+autocentrum\.pl[^\s"\']*opinie[^\s"\']*)',
                        page_text,
                    )
                    if op_match:
                        opinions_url = op_match.group(1)
                    else:
                        # Construct typical opinions URL pattern
                        base = model_url.rstrip("/")
                        opinions_url = base + "/opinie/"

                    # Scrape up to 50 opinions across pages
                    opinions_scraped = 0
                    page_num = 1
                    while opinions_scraped < 50 and page_num <= 5:
                        try:
                            _time.sleep(2)
                            if page_num == 1:
                                op_page_url = opinions_url
                            else:
                                op_page_url = opinions_url.rstrip("/") + f"/{page_num}/"
                            op_result = await mcp.call("browser_navigate", {"url": op_page_url})
                            op_text = ""
                            if isinstance(op_result, dict):
                                op_text = op_result.get("text", op_result.get("content", ""))
                            elif isinstance(op_result, str):
                                op_text = op_result

                            if not op_text or len(op_text) < 100:
                                break

                            # Split opinions by common separators (newlines + rating patterns)
                            opinion_blocks = _re.split(r"\n{2,}", op_text)
                            found_on_page = 0
                            for block in opinion_blocks:
                                block = block.strip()
                                if len(block) < 30:
                                    continue
                                # Skip blocks that look like navigation/headers
                                if any(kw in block.lower() for kw in ["cookie", "regulamin", "newsletter", "reklam"]):
                                    continue

                                # Extract rating from block
                                op_rating: float | None = None
                                r_match = _re.search(r"(\d+(?:[.,]\d+)?)\s*/\s*10", block)
                                if r_match:
                                    try:
                                        op_rating = float(r_match.group(1).replace(",", "."))
                                    except ValueError:
                                        pass
                                if op_rating is None:
                                    r_match2 = _re.search(r"(\d)\s*/\s*5", block)
                                    if r_match2:
                                        try:
                                            op_rating = float(r_match2.group(1)) * 2
                                        except ValueError:
                                            pass

                                if len(block) >= 30:
                                    op_emb = _autocentrum_embed(block) if len(block) >= 50 else None
                                    op_emb_str = (
                                        f"[{','.join(str(x) for x in op_emb)}]"
                                        if op_emb else None
                                    )
                                    cur.execute(
                                        """
                                        INSERT INTO autocentrum_reviews
                                            (model_id, source, content, rating, url, embedding)
                                        VALUES (%s, 'owner', %s, %s, %s, %s)
                                        """,
                                        (model_id, block[:2000], op_rating, op_page_url, op_emb_str),
                                    )
                                    op_count += 1
                                    found_on_page += 1
                                    opinions_scraped += 1
                                    if opinions_scraped >= 50:
                                        break

                            if found_on_page == 0:
                                break  # No more opinions
                            page_num += 1
                        except Exception as op_exc:
                            print(f"[scrape-autocentrum] opinions page {page_num} error: {op_exc}", flush=True)
                            break
            except Exception as exc:
                print(f"[scrape-autocentrum] browser-mcp error: {exc}", flush=True)
            return ed_count, op_count

        scrape_result: dict = {}

        def _run_scrape() -> None:
            try:
                ed, op = asyncio.run(_scrape_async())
                scrape_result["ed"] = ed
                scrape_result["op"] = op
            except Exception as exc:
                print(f"[scrape-autocentrum] thread error: {exc}", flush=True)
                scrape_result["ed"] = 0
                scrape_result["op"] = 0

        t = threading.Thread(target=_run_scrape)
        t.start()
        t.join(timeout=120)
        if t.is_alive():
            # Thread timed out — don't mark done, report failure
            editorial_count = 0
            opinion_count = 0
            _timed_out = True
        else:
            editorial_count = scrape_result.get("ed", 0)
            opinion_count = scrape_result.get("op", 0)
            _timed_out = False

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    if _timed_out:
        return f"⚠️ autocentrum: scrape {make} {model} timeout po 120s — brak danych w DB"

    # 5. Mark done in queue
    for item in queue:
        if item["make"] == make and item["model"] == model:
            item["done"] = True
    _autocentrum_save_queue(queue)

    return (
        f"✅ autocentrum scrape: {make} {model} — "
        f"{editorial_count} fragm. recenzji + {opinion_count} opinii właścicieli zapisanych do bazy\n"
        f"URL: {model_url}"
    )


# ---------------------------------------------------------------------------
# Skill handler: vinhunter-researcher
# ---------------------------------------------------------------------------

def _handle_vinhunter_researcher() -> str:
    """
    Research new VIN data sources weekly.
    Brave Search → LLM scoring → audit report → Telegram summary.
    """
    from mcp_client import MCPClient

    # 1. List existing plugin categories
    async def _list_plugins() -> list[str]:
        try:
            async with MCPClient(_MCP_SERVERS["fs-vinhunter"]) as mcp:
                result = await mcp.call("fs_list_dir", {"path": "backend/plugins"})
                lines = str(result).splitlines()
                return [line.split()[-1] for line in lines if line.strip().startswith("D")]
        except Exception as exc:
            print(f"[vinhunter-researcher] list_plugins error: {exc}", flush=True)
            return []

    def _run_list() -> list[str]:
        box: dict = {}
        def _t():
            box["v"] = asyncio.run(_list_plugins())
        t = threading.Thread(target=_t)
        t.start()
        t.join(timeout=30)
        if t.is_alive():
            print("[vinhunter-researcher] MCP list_plugins timeout", flush=True)
        return box.get("v", [])

    existing_plugins = _run_list()

    # 2. Brave Search — deduplicate by domain
    queries = [
        "VIN API EU free 2026",
        "car history database API Europe",
        "vehicle registry open data API",
    ]
    raw_results: list[dict] = []
    seen_domains: set[str] = set()
    for q in queries:
        for r in _brave_search(q, count=5):
            url = r.get("url", "")
            parts = url.split("/")
            domain = parts[2] if len(parts) > 2 else url
            if domain and domain not in seen_domains:
                seen_domains.add(domain)
                raw_results.append(r)

    if not raw_results:
        return "⚠️ vinhunter-researcher: Brave Search zwrócił 0 wyników. Sprawdź BRAVE_API_KEY."

    # 3. LLM analysis
    existing_str = ", ".join(existing_plugins) if existing_plugins else "brak danych"
    results_str = "\n".join(
        f"- {r.get('title', '')}: {r.get('url', '')} — {r.get('snippet', '')}"
        for r in raw_results
    )
    prompt = (
        "Jesteś ekspertem od OSINT dla pojazdów. Analizujesz nowe źródła danych VIN.\n\n"
        f"Istniejące pluginy VINhunter (kategorie): {existing_str}\n\n"
        f"Wyniki wyszukiwania:\n{results_str}\n\n"
        "Dla każdego NOWEGO źródła oceń na 4 osiach:\n"
        "- Typ: API REST=5, scraping=3, open data=3\n"
        "- Pokrycie: EU=5, global=3, US=1\n"
        "- Koszt: free=5, freemium=3, paid=1\n"
        "- Trudność: easy=5, medium=3, hard=1\n"
        "Score łączny: 0-20\n\n"
        "Wyjście:\n"
        "1. Tabela markdown: Nazwa | URL | Typ | Pokrycie | Koszt | Trudność | Score\n"
        "2. Sekcja '## Top 3 do implementacji' z krótkim opisem każdego i dokładną nazwą "
        "do użycia jako argument pluginu (snake_case, np. rdw_open_data)"
    )

    llm_result = llm_client.call_llm(prompt, tier="medium", skill="vinhunter-research")
    if llm_result is None:
        return "⚠️ vinhunter-researcher: LLM returned None"
    report_text = llm_result.get("text", "")
    if not report_text:
        return f"⚠️ vinhunter-researcher: LLM error: {llm_result.get('error')}"

    # 4. Write report
    date_str = datetime.now().strftime("%Y-%m-%d")
    report_path = _AUDIT_DIR / f"vinhunter-research-{date_str}.md"
    report_path.write_text(
        f"# VINhunter Research — {date_str}\n\n{report_text}",
        encoding="utf-8",
    )

    # 5. Extract top source name (first snake_case name in Top 3 section)
    import re as _re
    top_match = _re.search(r"##\s*Top 3[^\n]*\n+.*?`?([a-z][a-z0-9_]+)`?", report_text, _re.DOTALL)
    top_safe = top_match.group(1).strip() if top_match else "nieznane"

    return (
        f"🔍 VINhunter research — {date_str}\n"
        f"Raport: audit/vinhunter-research-{date_str}.md\n"
        f"Najlepsze źródło: {top_safe}\n\n"
        f"Napisać plugin? /skill vinhunter-write-plugin {top_safe}"
    )


# ---------------------------------------------------------------------------
# Skill handler: vinhunter-plugin-writer
# ---------------------------------------------------------------------------

def _handle_vinhunter_plugin_writer(args: str = "") -> str:
    """
    Write a VINhunter plugin for a named source.
    args: source name from research report (e.g. "rdw_open_data")
    """
    import re as _re
    from mcp_client import MCPClient

    source_name = args.strip()
    if not source_name:
        return "⚠️ Podaj nazwę źródła: /skill vinhunter-write-plugin [source_name]"

    safe_name = source_name.lower().replace(" ", "_").replace("-", "_")

    # 1. Find latest research report
    reports = sorted(_AUDIT_DIR.glob("vinhunter-research-*.md"), reverse=True)
    if not reports:
        return "⚠️ Brak raportu research. Uruchom: /skill vinhunter-research"
    report_content = reports[0].read_text(encoding="utf-8")

    # 2. Read existing plugin templates via mcp-fs-vinhunter
    async def _read_templates() -> tuple[str, str]:
        try:
            async with MCPClient(_MCP_SERVERS["fs-vinhunter"]) as mcp:
                nhtsa = await mcp.call(
                    "fs_read_file", {"path": "backend/plugins/vin_decode/nhtsa.py"}
                )
                try:
                    rdw = await mcp.call(
                        "fs_read_file", {"path": "backend/plugins/registries/nl_rdw.py"}
                    )
                except Exception:
                    rdw = ""
                return str(nhtsa), str(rdw)
        except Exception as exc:
            return "", f"# template read error: {exc}"

    def _run_templates() -> tuple[str, str]:
        box: dict = {}
        def _t():
            box["v"] = asyncio.run(_read_templates())
        t = threading.Thread(target=_t)
        t.start()
        t.join(timeout=30)
        if t.is_alive():
            print("[plugin-writer] template read timeout", flush=True)
        return box.get("v", ("", ""))

    nhtsa_code, rdw_code = _run_templates()

    # 3. LLM generates plugin code
    prompt = (
        f"Jesteś ekspertem Python piszącym pluginy do projektu VINhunter — OSINT dla historii pojazdów.\n\n"
        f"Napisz kompletny plugin Python dla źródła: **{source_name}**\n\n"
        f"Informacje o źródle z raportu research:\n{report_content}\n\n"
        f"=== Wzorzec 1: nhtsa.py (vin_decode) ===\n{nhtsa_code}\n\n"
        f"=== Wzorzec 2: nl_rdw.py (registries) ===\n{rdw_code}\n\n"
        "Wymagania:\n"
        "- Dziedzicz po SourcePlugin z plugins.base\n"
        "- Zaimplementuj async def search_by_vin(self, vin, **kwargs) -> PluginResult\n"
        "- Używaj httpx.AsyncClient dla requestów HTTP\n"
        "- Obsługuj błędy: timeout, connection error, 4xx/5xx → SourceStatus.ERROR lub NO_DATA\n"
        "- Wybierz kategorię: SourceCategory.VIN_DECODE / REGISTRY / DAMAGE / PHOTO_OSINT / ADS_ARCHIVE\n"
        "- Dodaj krótki docstring z URL API (jeśli znany z raportu)\n\n"
        "Zwróć TYLKO kod Python, bez wyjaśnień i bez markdown fences."
    )

    llm_result = llm_client.call_llm(
        prompt, tier="hard", max_tokens=2048, skill="vinhunter-plugin-writer"
    )
    if llm_result is None:
        return "⚠️ vinhunter-plugin-writer: LLM returned None"
    plugin_code = llm_result.get("text", "").strip()
    if not plugin_code:
        return f"⚠️ vinhunter-plugin-writer: LLM error: {llm_result.get('error')}"

    # Strip markdown fences if LLM added them anyway
    plugin_code = _re.sub(r"^```python\n?", "", plugin_code)
    plugin_code = _re.sub(r"\n?```$", "", plugin_code).strip()

    # 4. Determine category from generated code
    category_dir = "vin_decode"
    if "REGISTRY" in plugin_code:
        category_dir = "registries"
    elif "DAMAGE" in plugin_code:
        category_dir = "damage"
    elif "PHOTO_OSINT" in plugin_code:
        category_dir = "osint_photo"
    elif "ADS_ARCHIVE" in plugin_code:
        category_dir = "ads_archive"

    plugin_path = f"backend/plugins/{category_dir}/{safe_name}.py"
    branch_name = f"hermes/plugin-{safe_name}"

    # 5. Write via mcp-fs-vinhunter
    async def _write_and_commit() -> str:
        async with MCPClient(_MCP_SERVERS["fs-vinhunter"]) as mcp:
            try:
                await mcp.call("git_checkout_branch", {"branch_name": branch_name})
            except Exception as exc:
                print(f"[plugin-writer] git checkout warn: {exc}", flush=True)

            await mcp.call("fs_write_file", {"path": plugin_path, "content": plugin_code})

            try:
                commit_out = await mcp.call(
                    "git_commit",
                    {"message": f"feat(plugins): add {safe_name} plugin (hermes-generated)"},
                )
                return str(commit_out)
            except Exception as exc:
                return f"(git commit warn: {exc})"

    def _run_write() -> str:
        box: dict = {}
        def _t():
            try:
                box["v"] = asyncio.run(_write_and_commit())
            except Exception as exc:
                box["v"] = f"error: {exc}"
        t = threading.Thread(target=_t)
        t.start()
        t.join(timeout=60)
        if t.is_alive():
            print("[plugin-writer] write_and_commit timeout", flush=True)
        return box.get("v", "timeout")

    write_result = _run_write()

    # 6. Alumnium health check (optional)
    health_note = ""
    try:
        async def _health() -> bool:
            async with MCPClient(_MCP_SERVERS["alumnium"]) as mcp:
                result = await mcp.call(
                    "al_navigate", {"url": "http://host.docker.internal:8200/health"}
                )
                return "navigated" in str(result).lower()

        def _run_health() -> bool:
            box: dict = {}
            def _t():
                try:
                    box["v"] = asyncio.run(_health())
                except Exception:
                    box["v"] = False
            t = threading.Thread(target=_t)
            t.start()
            t.join(timeout=20)
            return box.get("v", False)

        if _run_health():
            health_note = "VINhunter ✅ działa — zrestartuj backend żeby załadować plugin."
        else:
            health_note = "VINhunter nie odpowiada (OK jeśli nie jest uruchomiony)."
    except Exception:
        health_note = "Alumnium check pominięty."

    return (
        f"✅ Plugin `{safe_name}` napisany.\n"
        f"Plik: {plugin_path}\n"
        f"Branch: `{branch_name}` (lokalny)\n"
        f"Git: {write_result}\n"
        f"{health_note}\n\n"
        f"Następny krok: zrestartuj VINhunter i zweryfikuj plugin."
    )


def _cron_execute_skill(skill_name: str) -> str:
    """Execute a skill by name (same routing as _make_reply for SKILL: prefix)."""
    if skill_name in ("scan-rss", "scan-rss-opportunities"):
        return _handle_scan_rss()
    if skill_name in ("crypto-arbitrage", "crypto-arbitrage-watch"):
        return _handle_crypto_arbitrage()
    if skill_name in ("domain-flip", "domain-flip-radar"):
        return _handle_domain_flip()
    if skill_name in ("client-followup",):
        return _handle_client_followup()
    if skill_name == "auto-todo":
        return _handle_auto_todo()
    if skill_name == "classify-tabs":
        return _handle_classify_tabs()
    if skill_name == "daily-digest":
        return _handle_daily_digest()
    if skill_name == "recompute-importance":
        return _handle_recompute_importance()
    if skill_name == "check-confirmations":
        return _handle_check_confirmations()
    if skill_name in ("review-learn", "review-projects"):
        return _handle_review_learn()
    if skill_name == "test-rag-endpoint":
        return _handle_test_rag()
    if skill_name in ("test-trading", "test-selfmadeagent"):
        return _handle_service_health(skill_name)
    if skill_name == "pool-monitor":
        return _handle_pool_monitor()
    if skill_name == "scrape-autocentrum":
        return _handle_scrape_autocentrum()
    if skill_name == "vinhunter-researcher":
        return _handle_vinhunter_researcher()
    return f"[cron] skill '{skill_name}' not supported for cron."


def _has_alert(result: str) -> bool:
    """Check if cron result contains an alert worth notifying about."""
    alert_markers = ["alert", "⚠️", "⛔", "suspicious", "ALERT", "threshold"]
    result_lower = result.lower()
    return any(m.lower() in result_lower for m in alert_markers)


def _handle_recompute_importance() -> str:
    """Recompute importance_score for all tabs using time_open + revisit + domain_weight."""
    try:
        import psycopg2
        conn = psycopg2.connect(_RECALL_DSN)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            UPDATE hermes_tabs t
            SET importance_score = ROUND((
                LEAST(EXTRACT(EPOCH FROM (COALESCE(last_seen_at, captured_at) - COALESCE(first_seen_at, captured_at))) / 3600.0 / 168.0, 1.0) * 0.3
                + LEAST(COALESCE(revisit_count, 1)::float / 50.0, 1.0) * 0.4
                + COALESCE(dw.base_weight, 1.0) / 5.0 * 0.3
            )::numeric, 4)
            FROM hermes_domain_weights dw
            WHERE t.domain = dw.domain
        """)
        updated_with_domain = cur.rowcount
        # Also update tabs without domain weights (domain_weight = 1.0 default)
        cur.execute("""
            UPDATE hermes_tabs t
            SET importance_score = ROUND((
                LEAST(EXTRACT(EPOCH FROM (COALESCE(last_seen_at, captured_at) - COALESCE(first_seen_at, captured_at))) / 3600.0 / 168.0, 1.0) * 0.3
                + LEAST(COALESCE(revisit_count, 1)::float / 50.0, 1.0) * 0.4
                + 1.0 / 5.0 * 0.3
            )::numeric, 4)
            WHERE NOT EXISTS (SELECT 1 FROM hermes_domain_weights dw WHERE dw.domain = t.domain)
        """)
        updated_no_domain = cur.rowcount
        conn.close()
        total = updated_with_domain + updated_no_domain
        return f"Recomputed importance_score for {total} tabs."
    except Exception as exc:
        return f"Error recomputing importance: {exc}"


def _handle_confirm(arg: str) -> str:
    """Handle /confirm command — approve or deny pending tab confirmations."""
    try:
        import psycopg2 as pg2
        conn = pg2.connect(_RECALL_DSN)
        conn.autocommit = True
        cur = conn.cursor()

        if not arg or arg.strip().lower() == "list":
            cur.execute(
                "SELECT id, domain, title, url, requested_at "
                "FROM hermes_tab_confirmations WHERE status = 'pending' "
                "ORDER BY requested_at DESC LIMIT 10"
            )
            rows = cur.fetchall()
            conn.close()
            if not rows:
                return "Brak oczekujących potwierdzeń."
            lines = ["Oczekujące potwierdzenia:", ""]
            for r in rows:
                cid, domain, title, url, req_at = r
                t = (title or "(brak tytułu)")[:40]
                d = req_at.strftime("%m-%d %H:%M") if req_at else "?"
                lines.append(f"  #{cid} [{d}] {domain}")
                lines.append(f"    {t}")
                lines.append(f"    /confirm {cid}  |  /confirm deny {cid}")
                lines.append("")
            return "\n".join(lines)

        parts = arg.strip().split()
        if parts[0].lower() == "deny" and len(parts) >= 2:
            try:
                cid = int(parts[1])
            except ValueError:
                return "Użycie: /confirm deny <id>"
            cur.execute(
                "UPDATE hermes_tab_confirmations SET status = 'denied', resolved_at = NOW() "
                "WHERE id = %s AND status = 'pending'", (cid,),
            )
            conn.close()
            return f"Odmówiono dostępu do #{cid}." if cur.rowcount > 0 else f"#{cid} nie znalezione."

        if parts[0].lower() == "all":
            cur.execute(
                "UPDATE hermes_tab_confirmations SET status = 'approved', resolved_at = NOW() "
                "WHERE status = 'pending'"
            )
            count = cur.rowcount
            conn.close()
            return f"Zatwierdzono {count} oczekujących." if count else "Brak oczekujących."

        try:
            cid = int(parts[0])
        except ValueError:
            return "Użycie: /confirm [id | all | deny <id> | list]"
        cur.execute(
            "UPDATE hermes_tab_confirmations SET status = 'approved', resolved_at = NOW() "
            "WHERE id = %s AND status = 'pending'", (cid,),
        )
        conn.close()
        return f"Zatwierdzono #{cid}. Ingest przeczyta tab w następnym cyklu." if cur.rowcount > 0 else f"#{cid} nie znalezione."

    except Exception as exc:
        return f"Confirm error: {exc}"


def _handle_check_confirmations() -> str:
    """Check for pending domain confirmations and return alert if any exist."""
    try:
        conn = _get_db_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM hermes_tab_confirmations WHERE status = 'pending'")
            count = cur.fetchone()[0]
        if count == 0:
            return "Brak oczekujących potwierdzeń."
        return f"⚠️ ALERT: {count} tabów czeka na potwierdzenie. Użyj /confirm żeby zobaczyć listę."
    except Exception as exc:
        return f"Check confirmations error: {exc}"


_REVIEW_LEARN_LOG = Path(os.environ.get("HERMES_AUDIT_DIR", "/audit")) / "review-learn-reviewed.json"
_REVIEW_LEARN_PROJECTS = [
    "RAG/backend",
    "Selfmadeagent/orchestrator",
    "VIN OSINT/vinhunter",
]
_REVIEW_LEARN_EXTENSIONS = {".py"}
_REVIEW_LEARN_SKIP = {"__pycache__", ".pyc", "node_modules", ".git", "__init__.py"}


def _review_learn_get_reviewed() -> list[str]:
    """Load list of already-reviewed file paths."""
    try:
        if _REVIEW_LEARN_LOG.exists():
            return json.loads(_REVIEW_LEARN_LOG.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _review_learn_mark_reviewed(filepath: str) -> None:
    """Add filepath to reviewed list."""
    reviewed = _review_learn_get_reviewed()
    if filepath not in reviewed:
        reviewed.append(filepath)
    # Keep last 200 entries
    reviewed = reviewed[-200:]
    _REVIEW_LEARN_LOG.write_text(json.dumps(reviewed, ensure_ascii=False), encoding="utf-8")


def _review_learn_pick_file() -> tuple[str, str] | None:
    """
    Pick the next unreviewed Python file from workspace.
    Returns (relative_path, content) or None.
    """
    workspace = Path("/workspace/ro")
    reviewed = set(_review_learn_get_reviewed())
    candidates: list[Path] = []

    for project_dir in _REVIEW_LEARN_PROJECTS:
        scan_dir = workspace / project_dir
        if not scan_dir.is_dir():
            continue
        for root, dirs, files in os.walk(scan_dir):
            # Skip unwanted dirs
            dirs[:] = [d for d in dirs if d not in _REVIEW_LEARN_SKIP and not d.startswith(".")]
            for fname in sorted(files):
                if any(skip in fname for skip in _REVIEW_LEARN_SKIP):
                    continue
                fpath = Path(root) / fname
                if fpath.suffix not in _REVIEW_LEARN_EXTENSIONS:
                    continue
                rel = str(fpath.relative_to(workspace))
                if rel in reviewed:
                    continue
                # Size check
                try:
                    size = fpath.stat().st_size
                    if size < 50 or size > 15000:
                        continue
                except OSError:
                    continue
                candidates.append(fpath)

    if not candidates:
        # All reviewed — reset and start over
        _REVIEW_LEARN_LOG.write_text("[]", encoding="utf-8")
        return None

    chosen = candidates[0]
    rel = str(chosen.relative_to(workspace))
    try:
        content = chosen.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    return (rel, content)


def _handle_review_learn() -> str:
    """Pick a code file, send to ChatGPT for review, return suggestions."""
    pick = _review_learn_pick_file()
    if pick is None:
        return "Self-learn: wszystkie pliki przejrzane w tej rundzie. Reset listy — następny cykl zacznie od nowa."

    rel_path, content = pick

    # Truncate if needed (Ollama fallback uses this full content)
    if len(content) > 8000:
        content = content[:8000] + "\n\n... (truncated)"

    # Load previous reviews for this file (so model proposes NEW suggestions)
    prior_reviews_block = ""
    try:
        rel_parts = Path(rel_path).parts
        proj = (rel_parts[0] if rel_parts else "unknown").replace(" ", "_")
        flat = "_".join(rel_parts[1:]) or rel_parts[0]
        review_dir = Path(os.environ.get("HERMES_AUDIT_DIR", "/audit")) / "reviews" / proj
        if review_dir.is_dir():
            prior = sorted(review_dir.glob(f"{flat}__*.md"))[-3:]
            if prior:
                snippets = []
                for p in prior:
                    try:
                        body = p.read_text(encoding="utf-8", errors="replace")
                        snippets.append(f"### {p.name}\n{body[:1500]}")
                    except Exception:
                        continue
                if snippets:
                    prior_reviews_block = (
                        "\n\nPOPRZEDNIE REVIEW TEGO PLIKU (NIE powtarzaj tych sugestii — "
                        "zaproponuj NOWE lub wskaż które zostały wdrożone w obecnym kodzie):\n"
                        + "\n\n".join(snippets)
                    )
    except Exception as exc:
        print(f"[review-learn] failed to load prior reviews: {exc}", flush=True)

    full_prompt = (
        f"Jesteś senior code reviewer. Przejrzyj poniższy plik i zaproponuj "
        f"konkretne ulepszenia (max 5 punktów). Skup się na: bugach, security, "
        f"wydajności, czytelności. Odpowiadaj po polsku, zwięźle.\n\n"
        f"Plik: {rel_path}\n"
        f"```python\n{content}\n```"
        f"{prior_reviews_block}"
    )

    # Build short ChatGPT prompt: pre-summarize via OpenRouter free tier
    # ChatGPT browser UI chokes on 8000-char paste — keep prompt under ~2500 chars.
    if len(content) > 1500:
        summarize_prompt = (
            f"Streszcz poniższy plik Python w max 800 znakach. Zwróć: (1) cel pliku w 1 zdaniu, "
            f"(2) listę kluczowych funkcji/klas, (3) 2-3 konkretne podejrzane fragmenty (numer linii + "
            f"powód) jeśli zauważysz problemy z bugami/security/wydajnością. Zwięźle, po polsku.\n\n"
            f"Plik: {rel_path}\n```python\n{content}\n```"
        )
        sum_result = llm_client.call_llm(summarize_prompt, tier="easy", max_tokens=400, skill="review-learn-summarize")
        summary = (sum_result.get("text") or "").strip()
        if summary and not sum_result.get("error"):
            chatgpt_prompt = (
                f"Jesteś senior code reviewer. Na podstawie poniższego streszczenia pliku Python "
                f"zaproponuj 5 konkretnych ulepszeń (bugi, security, wydajność, czytelność). "
                f"Zwięźle po polsku.\n\n"
                f"Plik: {rel_path}\n"
                f"Streszczenie (od pre-procesora):\n{summary}"
            )
            print(f"[review-learn] summarized {len(content)}ch -> {len(summary)}ch via {sum_result.get('model')}", flush=True)
        else:
            # Summary failed → use truncated raw content as last resort
            chatgpt_prompt = full_prompt[:2500]
            print(f"[review-learn] summarize failed ({sum_result.get('error')}), sending truncated raw to ChatGPT", flush=True)
    else:
        chatgpt_prompt = full_prompt

    answer = ""
    duration = 0
    model_used = ""
    tier_used = ""
    cdp_error = ""

    # 1. Primary: ChatGPT via browser-mcp CDP (matches skill spec review-learn.md)
    async def _ask():
        from mcp_client import MCPClient
        async with MCPClient() as mcp:
            result = await mcp.call(
                "browser_ask_chatgpt",
                {"prompt": chatgpt_prompt, "wait_seconds": 120, "force_new_conversation": False},
            )
            return result

    try:
        cdp_result = asyncio.run(_ask())
        if isinstance(cdp_result, dict):
            answer = cdp_result.get("answer", "") or ""
            duration = cdp_result.get("duration_ms", 0)
        else:
            answer = str(cdp_result) if cdp_result else ""
            duration = 0
        if answer.strip():
            model_used = "chatgpt-cdp"
            tier_used = "chatgpt"
            print(f"[review-learn] ChatGPT OK for {rel_path} ({duration}ms)", flush=True)
        else:
            cdp_error = "empty answer from ChatGPT"
    except Exception as exc:
        cdp_error = str(exc)
        print(f"[review-learn] ChatGPT failed ({cdp_error}), falling back to Ollama hard tier", flush=True)

    # 2. Fallback: llm-proxy hard tier (Mac Studio qwen3-coder-next 80B)
    if not answer.strip():
        hard_result = llm_client.call_llm(full_prompt, tier="hard", skill="review-learn")
        hard_error = hard_result.get("error") or ""
        if not hard_error:
            answer = hard_result.get("text", "").strip()
            duration = hard_result.get("latency_ms", 0)
            model_used = hard_result.get("model", "qwen3-coder-next:q4_K_M")
            tier_used = "ollama-fallback"
            print(f"[review-learn] hard tier OK for {rel_path} ({duration}ms)", flush=True)
        else:
            _review_learn_mark_reviewed(rel_path)
            return f"Self-learn error ({rel_path}): ChatGPT={cdp_error}, hard={hard_error}"

    _review_learn_mark_reviewed(rel_path)

    if not answer:
        return f"Self-learn: brak odpowiedzi (hard tier + ChatGPT CDP) dla {rel_path}."

    # Save to persistent memory
    try:
        mem.remember(f"Code review [{rel_path}]: {answer[:300]}", category="code_review")
    except Exception as exc:
        print(f"[review-learn] save_persistent failed: {exc}", flush=True)

    # Save full review to audit/reviews/<project>/<flattened-path>__<ts>.md
    try:
        rel_parts = Path(rel_path).parts
        project = (rel_parts[0] if rel_parts else "unknown").replace(" ", "_")
        flat_name = "_".join(rel_parts[1:]) or rel_parts[0]
        ts_compact = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        review_dir = Path(os.environ.get("HERMES_AUDIT_DIR", "/audit")) / "reviews" / project
        review_dir.mkdir(parents=True, exist_ok=True)
        review_path = review_dir / f"{flat_name}__{ts_compact}.md"
        print(f"[review-learn] writing {review_path}", flush=True)
        review_path.write_text(
            f"# Self-learn review: {rel_path}\n\n"
            f"- ts: {ts_compact}\n"
            f"- tier: {tier_used}\n"
            f"- model: {model_used}\n"
            f"- duration_ms: {duration}\n\n"
            f"---\n\n{answer}\n",
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"[review-learn] failed to write review file: {exc}", flush=True)

    # Append to audit log
    try:
        log_path = Path(os.environ.get("HERMES_AUDIT_DIR", "/audit")) / "review-learn.log"
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "file": rel_path,
            "answer_len": len(answer),
            "duration_ms": duration,
            "tier": tier_used,
            "model_used": model_used,
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        print(f"[review-learn] audit log write failed: {exc}", flush=True)

    # Telegram: short summary only — full review is on disk
    review_rel = ""
    try:
        review_rel = str(review_path.relative_to(Path(os.environ.get("HERMES_AUDIT_DIR", "/audit")).parent))
    except Exception:
        review_rel = str(review_path) if 'review_path' in locals() else "(zapis nieudany)"

    # Extract first ~3 bullet points / first 600 chars as preview
    lines = [ln for ln in answer.splitlines() if ln.strip()]
    bullets = [ln for ln in lines if ln.lstrip().startswith(("-", "*", "1.", "2.", "3.", "4.", "5."))]
    if len(bullets) >= 2:
        preview = "\n".join(bullets[:3])
    else:
        preview = answer[:600]
    if len(preview) > 700:
        preview = preview[:700] + "…"

    return (
        f"📝 Review: {rel_path}\n"
        f"({duration}ms, {tier_used}, {model_used})\n\n"
        f"{preview}\n\n"
        f"📂 pełna treść: {review_rel}"
    )


def _handle_daily_digest() -> str:
    """Generate daily digest from cron.log entries in last 24h."""
    log_path = _cron_log()
    if not log_path.exists():
        return "Daily Digest — brak logów."

    cutoff = time.time() - 86400
    stats: dict[str, dict] = {}  # skill → {runs, ok, failed, alerts, last_preview}
    total_runs = 0

    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        # Parse timestamp
        ts_str = entry.get("ts", "")
        try:
            from datetime import datetime as dt
            entry_time = dt.fromisoformat(ts_str).timestamp()
        except (ValueError, TypeError):
            continue

        if entry_time < cutoff:
            continue

        skill = entry.get("skill", "unknown")
        success = entry.get("success", False)
        preview = entry.get("preview", "")

        if skill not in stats:
            stats[skill] = {"runs": 0, "ok": 0, "failed": 0, "alerts": 0, "last_preview": ""}

        stats[skill]["runs"] += 1
        total_runs += 1
        if success:
            stats[skill]["ok"] += 1
        else:
            stats[skill]["failed"] += 1
        if _has_alert(preview):
            stats[skill]["alerts"] += 1
        stats[skill]["last_preview"] = preview[:100]

    if not stats:
        return "Daily Digest — brak aktywności w ostatnich 24h."

    # Memory stats
    try:
        session_count = mem.session_count()
        persistent_count = mem.persistent_count()
    except Exception:
        session_count = 0
        persistent_count = 0

    # Tab stats
    tab_count = 0
    try:
        conn = _get_db_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM hermes_tabs")
            tab_count = cur.fetchone()[0]
    except Exception:
        pass

    lines = [
        f"Daily Digest ({datetime.now().strftime('%Y-%m-%d')})",
        f"Total cron runs: {total_runs}",
        "",
    ]

    for skill, s in sorted(stats.items()):
        alert_tag = f" ({s['alerts']} alerts)" if s["alerts"] else ""
        fail_tag = f", {s['failed']} failed" if s["failed"] else ""
        lines.append(f"  {skill}: {s['ok']} ok{fail_tag}{alert_tag}")
        if s["last_preview"]:
            lines.append(f"    Last: {s['last_preview'][:80]}")

    lines.append("")
    lines.append(f"Memory: {session_count} sessions, {persistent_count} facts")
    lines.append(f"Tabs indexed: {tab_count}")

    return "\n".join(lines)


def _cron_send_to_telegram(text: str) -> None:
    """Write a cron result to outbox for delivery via Telegram."""
    if not _CRON_CHAT_ID:
        print("[cron] no TELEGRAM_CHAT_ID set, skipping delivery", flush=True)
        return
    ts = int(time.time())
    payload = {
        "reply_to_ts": 0,
        "reply_to_chat_id": _CRON_CHAT_ID,
        "text": text,
        "attachments": [],
    }
    filename = f"cron_{ts}.json"
    (_outbox_dir() / filename).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _n8n_notify(event_type: str, skill_name: str, result: str, metadata: dict | None = None) -> bool:
    """POST event to n8n webhook. Returns True on success."""
    if not _N8N_WEBHOOK_URL:
        return False
    payload = {
        "source": "hermes",
        "event_type": event_type,
        "skill_name": skill_name,
        "result_preview": result[:2000],
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if metadata:
        payload["metadata"] = metadata
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(_N8N_WEBHOOK_URL, json=payload)
            resp.raise_for_status()
        print(f"[n8n] webhook OK for {skill_name} ({event_type})", flush=True)
        return True
    except Exception as exc:
        print(f"[n8n] webhook error: {exc}", flush=True)
        return False


def _handle_n8n(arg: str) -> str:
    """Handle /n8n command: status, test, trigger."""
    arg = arg.strip().lower()

    if not arg:
        # Status
        lines = ["n8n Integration", ""]
        if _N8N_WEBHOOK_URL:
            lines.append(f"  Webhook: {_N8N_WEBHOOK_URL}")
            lines.append("  Status: configured")
        else:
            lines.append("  Webhook: not configured")
            lines.append("  Set N8N_WEBHOOK_URL in .env to enable")
        lines.append("")
        lines.append("Commands:")
        lines.append("  /n8n — show status")
        lines.append("  /n8n test — send test event")
        lines.append("  /n8n trigger <skill> — run skill and send result to n8n")
        return "\n".join(lines)

    if arg == "test":
        if not _N8N_WEBHOOK_URL:
            return "n8n webhook not configured. Set N8N_WEBHOOK_URL in .env."
        ok = _n8n_notify("test", "hermes-test", "This is a test event from Hermes.")
        return "n8n test event sent." if ok else "n8n test event FAILED."

    # /n8n trigger <skill>
    parts = arg.split(None, 1)
    if parts[0] == "trigger" and len(parts) > 1:
        skill_name = parts[1]
        if not _N8N_WEBHOOK_URL:
            return "n8n webhook not configured. Set N8N_WEBHOOK_URL in .env."
        result = _cron_execute_skill(skill_name)
        ok = _n8n_notify("manual_trigger", skill_name, result)
        status = "sent to n8n" if ok else "n8n delivery FAILED"
        return f"Skill '{skill_name}' executed. Result {status}.\n\n{result[:500]}"

    return "Usage: /n8n [test | trigger <skill>]"


def _should_run_now(job: dict) -> bool:
    """Check if a cron job should run now."""
    if not job["enabled"]:
        return False
    now = time.time()
    if now - job["last_run"] < job["interval_s"]:
        return False
    # If run_at_hour is set, only run during that hour (local time)
    run_at = job.get("run_at_hour")
    if run_at is not None:
        current_hour = datetime.now().hour
        if current_hour != run_at:
            return False
    return True


def _cron_tick() -> None:
    """Run one cron check cycle. Called from the cron thread."""
    with _cron_lock:
        for skill_name, job in _CRON_JOBS.items():
            if not _should_run_now(job):
                continue

            print(f"[cron] running {skill_name}...", flush=True)
            t0 = time.monotonic()
            try:
                result = _cron_execute_skill(skill_name)
                latency_ms = int((time.monotonic() - t0) * 1000)
                job["last_run"] = time.time()

                # Smart notification based on job's notify setting
                notify_mode = job.get("notify", "always")
                should_notify = (
                    notify_mode == "always"
                    or (notify_mode == "on_alert" and _has_alert(result))
                )
                if should_notify:
                    header = f"[CRON] {job['description']}\n\n"
                    _cron_send_to_telegram(header + result)
                _n8n_notify("cron_result", skill_name, result)
                _append_cron_log(skill_name, True, latency_ms, result[:200])

                # Also save to session memory
                try:
                    mem.save_session(
                        f"[CRON] {skill_name}",
                        result,
                        skill_name=f"cron:{skill_name}",
                        latency_ms=latency_ms,
                    )
                except Exception as exc:
                    print(f"[cron] memory save error: {exc}", flush=True)

                print(f"[cron] {skill_name} done ({latency_ms}ms)", flush=True)
            except Exception as exc:
                latency_ms = int((time.monotonic() - t0) * 1000)
                job["last_run"] = time.time()  # don't retry immediately
                _append_cron_log(skill_name, False, latency_ms, str(exc))
                print(f"[cron] {skill_name} FAILED: {exc}", flush=True)


def _cron_loop() -> None:
    """Background thread: check cron every 60s."""
    print("[cron] scheduler started", flush=True)
    while _running:
        try:
            _cron_tick()
        except Exception as exc:
            print(f"[cron] tick error: {exc}", flush=True)
        # Sleep 60s in small increments for SIGTERM responsiveness
        for _ in range(60):
            if not _running:
                break
            time.sleep(1.0)
    print("[cron] scheduler stopped", flush=True)


def _handle_cron(arg: str) -> str:
    """Handle /cron command: list jobs, enable/disable."""
    arg = arg.strip().lower()

    # /cron — list all jobs
    if not arg:
        lines = ["Cron Scheduler", ""]
        with _cron_lock:
            for name, job in _CRON_JOBS.items():
                status = "ON" if job["enabled"] else "OFF"
                interval = job["interval_s"]
                if interval >= 86400:
                    interval_str = f"{interval // 86400}d"
                elif interval >= 3600:
                    interval_str = f"{interval // 3600}h"
                else:
                    interval_str = f"{interval // 60}m"
                last = "never" if job["last_run"] == 0 else datetime.fromtimestamp(job["last_run"]).strftime("%m-%d %H:%M")
                hour = f" @{job['run_at_hour']}:00" if job.get("run_at_hour") is not None else ""
                notify = job.get("notify", "always")
                notify_tag = f" [{notify}]" if notify != "always" else ""
                lines.append(f"  [{status}] {name} — every {interval_str}{hour}{notify_tag}")
                lines.append(f"    {job['description']}")
                lines.append(f"    Last run: {last}")
                lines.append("")
        lines.append("Use: /cron on|off <name>")
        return "\n".join(lines)

    # /cron on <name> or /cron off <name>
    parts = arg.split(None, 1)
    action = parts[0]
    target = parts[1] if len(parts) > 1 else ""

    if action in ("on", "off") and target:
        with _cron_lock:
            if target in _CRON_JOBS:
                _CRON_JOBS[target]["enabled"] = (action == "on")
                status = "ON" if action == "on" else "OFF"
                return f"Cron job '{target}' is now {status}."
            else:
                known = ", ".join(_CRON_JOBS.keys())
                return f"Unknown cron job '{target}'. Available: {known}"

    # /cron run <name> — force immediate run
    if action == "run" and target:
        with _cron_lock:
            if target in _CRON_JOBS:
                job = _CRON_JOBS[target]
                job["last_run"] = 0  # reset to trigger on next tick
                job["enabled"] = True
                return f"Cron job '{target}' will run on next tick (~60s)."
            else:
                known = ", ".join(_CRON_JOBS.keys())
                return f"Unknown cron job '{target}'. Available: {known}"

    return "Usage: /cron [on|off|run <name>]"


# ---------------------------------------------------------------------------
# Stub response generator
# ---------------------------------------------------------------------------

def _make_reply(text: str) -> str:
    if text.startswith("RECALL:"):
        query = text[len("RECALL:"):].strip()
        return _handle_recall(query)
    if text.startswith("REMEMBER:"):
        fact = text[len("REMEMBER:"):].strip()
        return _handle_remember(fact)
    if text.startswith("FORGET:"):
        query = text[len("FORGET:"):].strip()
        return _handle_forget(query)
    if text.startswith("HISTORY:"):
        arg = text[len("HISTORY:"):].strip()
        return _handle_history(arg)
    if text.startswith("TABS:"):
        arg = text[len("TABS:"):].strip()
        return _handle_tabs(arg)
    if text.startswith("CRON:"):
        arg = text[len("CRON:"):].strip()
        return _handle_cron(arg)
    if text.startswith("N8N:"):
        arg = text[len("N8N:"):].strip()
        return _handle_n8n(arg)
    if text.startswith("CONFIRM:"):
        arg = text[len("CONFIRM:"):].strip()
        return _handle_confirm(arg)
    if text.startswith("SKILL:"):
        # Parse "SKILL:skill-name args..."
        skill_payload = text[len("SKILL:"):].strip()
        parts = skill_payload.split(None, 1)
        skill_name = parts[0] if parts else ""
        skill_args = parts[1] if len(parts) > 1 else ""
        if skill_name == "research-question":
            return _handle_research(skill_args) if skill_args else "Podaj pytanie po /skill research-question."
        if skill_name == "test-mcp-server":
            server = skill_args.strip() if skill_args else "browser-mcp"
            return _handle_test_mcp(server)
        if skill_name == "test-rag-endpoint":
            return _handle_test_rag()
        if skill_name in ("test-trading", "test-selfmadeagent"):
            return _handle_service_health(skill_name)
        if skill_name in ("scan-rss", "scan-rss-opportunities"):
            return _handle_scan_rss()
        if skill_name in ("crypto-arbitrage", "crypto-arbitrage-watch"):
            return _handle_crypto_arbitrage()
        if skill_name in ("domain-flip", "domain-flip-radar"):
            return _handle_domain_flip()
        if skill_name in ("client-followup",):
            return _handle_client_followup()
        if skill_name in ("auto-todo", "auto-todo-extract"):
            return _handle_auto_todo()
        if skill_name in ("classify-tabs", "classify"):
            return _handle_classify_tabs()
        if skill_name in ("daily-digest", "digest"):
            return _handle_daily_digest()
        if skill_name == "recompute-importance":
            return _handle_recompute_importance()
        if skill_name in ("review-learn", "review-projects"):
            return _handle_review_learn()
        if skill_name in ("scrape-autocentrum",):
            return _handle_scrape_autocentrum(skill_args)
        if skill_name in ("vinhunter-research", "vinhunter-researcher"):
            return _handle_vinhunter_researcher()
        if skill_name in ("vinhunter-write-plugin", "vinhunter-plugin-writer"):
            return _handle_vinhunter_plugin_writer(skill_args)
        return f"[stub] skill '{skill_name}' nie jest jeszcze zaimplementowany."
    # Plain message → automatic research (Google + Ollama)
    if text.strip():
        return _handle_research(text.strip())
    return ""


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

def _write_outbox(ts: int, update_id: int, chat_id: Any, reply_ts: int, reply_text: str) -> None:
    filename = f"{ts}_{update_id}.json"
    payload = {
        "reply_to_ts": reply_ts,
        "reply_to_chat_id": chat_id,
        "text": reply_text,
        "attachments": [],
    }
    (_outbox_dir() / filename).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _move_to_processed(inbox_path: Path) -> None:
    dest = _processed_dir() / inbox_path.name
    inbox_path.rename(dest)


def _append_action_log(
    update_id: int,
    text: str,
    action_type: str = "plain",
    tier: str | None = None,
    model_used: str | None = None,
    latency_ms: int | None = None,
    prompt_len: int | None = None,
    response_len: int | None = None,
) -> None:
    entry: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": "bridge_processed",
        "action_type": action_type,
        "update_id": update_id,
        "text_preview": text[:80],
    }
    if tier is not None:
        entry["tier"] = tier
    if model_used is not None:
        entry["model_used"] = model_used
    if latency_ms is not None:
        entry["latency_ms"] = latency_ms
    if prompt_len is not None:
        entry["prompt_len"] = prompt_len
    if response_len is not None:
        entry["response_len"] = response_len
    with _actions_log().open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Single message processor
# ---------------------------------------------------------------------------

def _process_inbox_file(path: Path) -> None:
    try:
        if path.suffix == ".msg":
            # Plain text format: SKILL:name\nargs or plain text
            text = path.read_text(encoding="utf-8").strip()
            msg = {
                "text": text,
                "chat_id": 0,
                "ts": int(path.stem.split("_")[-1]) if "_" in path.stem else int(time.time()),
                "update_id": 0,
            }
        else:
            # JSON format (legacy)
            msg = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[bridge] failed to read {path.name}: {exc} — moving to processed", flush=True)
        try:
            _move_to_processed(path)
        except Exception:
            pass
        return

    chat_id = msg.get("chat_id")
    original_ts: int = int(msg.get("ts", 0))
    update_id: int = int(msg.get("update_id", 0))
    text: str = msg.get("text", "")

    # Determine action type
    if text.startswith("RECALL:"):
        action_type = "recall"
    elif text.startswith("SKILL:"):
        action_type = "skill"
    else:
        action_type = "plain"

    t0 = time.monotonic()
    reply_text = _make_reply(text)
    latency_ms = int((time.monotonic() - t0) * 1000)
    now_ts = int(time.time())

    _write_outbox(now_ts, update_id, chat_id, original_ts, reply_text)
    _move_to_processed(path)
    _append_action_log(update_id, text, action_type,
                       latency_ms=latency_ms,
                       prompt_len=len(text),
                       response_len=len(reply_text))

    # Auto-save to session memory
    try:
        skill_name = ""
        if action_type == "skill":
            parts = text[len("SKILL:"):].strip().split(None, 1)
            skill_name = parts[0] if parts else "skill"
        elif action_type == "recall":
            skill_name = "recall"
        mem.save_session(text, reply_text, skill_name=skill_name, latency_ms=latency_ms)
    except Exception as exc:
        print(f"[bridge] memory save error: {exc}", flush=True)

    print(f"[bridge] processed update_id={update_id} text_preview={text[:60]!r}", flush=True)


# ---------------------------------------------------------------------------
# Main poll loop
# ---------------------------------------------------------------------------

def main() -> None:
    _ensure_dirs()
    print("[bridge] starting, watching /audit/inbox/", flush=True)

    # Start cron scheduler thread
    cron_thread = threading.Thread(target=_cron_loop, daemon=True, name="cron-scheduler")
    cron_thread.start()

    while _running:
        try:
            # Sort by filename = chronological order (unix_ts prefix).
            # Accept both .json (legacy) and .msg (current) formats
            inbox_files = sorted([f for f in _inbox_dir().iterdir() if f.is_file() and f.suffix in ('.json', '.msg')])
            for path in inbox_files:
                if not _running:
                    break
                _process_inbox_file(path)
        except OSError as exc:
            print(f"[bridge] poll loop I/O error (volume issue?): {exc} — sleeping 30s", flush=True)
            for _ in range(300):
                if not _running:
                    break
                time.sleep(0.1)
            continue
        except Exception as exc:
            print(f"[bridge] poll loop error: {exc}", flush=True)

        # Sleep in small increments so SIGTERM is handled promptly.
        for _ in range(int(_POLL_INTERVAL * 10)):
            if not _running:
                break
            time.sleep(0.1)

    print("[bridge] stopped", flush=True)


if __name__ == "__main__":
    main()
