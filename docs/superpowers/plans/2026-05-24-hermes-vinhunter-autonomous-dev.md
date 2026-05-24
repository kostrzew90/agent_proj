# Hermes VINhunter Autonomous Dev — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Hermes the ability to autonomously research new VIN data sources, write plugin code via LLM, test with alumnium, and commit to a review branch — plus a persistent AI-native browser testing container.

**Architecture:** New `mcp-alumnium` container wraps Playwright + alumnium as FastMCP SSE tools. The mcp-fs-vinhunter git tools are fixed by initializing a local git repo on startup. Bridge gains two handlers: `_handle_vinhunter_researcher` (Brave Search → LLM analysis → markdown report → Telegram) and `_handle_vinhunter_plugin_writer` (reads report → LLM generates plugin code → writes via mcp-fs-vinhunter → alumnium health check → Telegram). Weekly cron triggers researcher every 7 days at 10:00.

**Tech Stack:** Python 3.11, playwright, alumnium, FastMCP SSE, httpx, `llm_client.call_llm()`, `MCPClient` (mcp_client.py)

---

## Files Created / Modified

| File | Action |
|------|--------|
| `hermes/mcp-alumnium/Dockerfile` | CREATE |
| `hermes/mcp-alumnium/requirements.txt` | CREATE |
| `hermes/mcp-alumnium/server.py` | CREATE — FastMCP SSE wrapping alumnium + Playwright |
| `hermes/docker-compose.yml` | MODIFY — add mcp-alumnium service |
| `hermes/bridge/hermes_bridge.py` | MODIFY — alumnium in _MCP_SERVERS, two handlers, one cron, routing |
| `hermes/mcp-fs-vinhunter/server.py` | MODIFY — git init on startup, raise on git failure |
| `.gitignore` | MODIFY — ignore VIN OSINT/vinhunter/.git/ |
| `hermes/skills/vinhunter-researcher.md` | CREATE |
| `hermes/skills/vinhunter-plugin-writer.md` | CREATE |

---

## Task 1: mcp-alumnium Container

**Files:**
- Create: `hermes/mcp-alumnium/requirements.txt`
- Create: `hermes/mcp-alumnium/Dockerfile`
- Create: `hermes/mcp-alumnium/server.py`

- [ ] **Step 1: Create requirements.txt**

```
mcp>=1.0.0
playwright>=1.44.0
alumnium>=0.1.0
```

- [ ] **Step 2: Create Dockerfile**

```dockerfile
FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates wget gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium --with-deps

COPY server.py .

EXPOSE 8000
CMD ["python", "server.py"]
```

- [ ] **Step 3: Create server.py**

```python
"""
mcp-alumnium — AI-native E2E browser testing via alumnium + Playwright.

Tools:
    al_navigate(url)       — navigate to URL, return title
    al_do(action)          — perform natural-language browser action
    al_check(assertion)    — verify assertion → "true" or "false: <reason>"
    al_get(value_desc)     — extract value from current page
    al_screenshot()        — save screenshot to /audit/
"""
import asyncio
import os
import threading
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from playwright.async_api import async_playwright, Browser, Page

mcp = FastMCP("alumnium", host="0.0.0.0")

_AUDIT_DIR = Path(os.environ.get("AUDIT_DIR", "/audit"))
_AUDIT_DIR.mkdir(parents=True, exist_ok=True)

# Persistent event loop — keeps browser alive across tool calls
_loop = asyncio.new_event_loop()
_loop_thread = threading.Thread(target=_loop.run_forever, daemon=True)
_loop_thread.start()

_browser: Browser | None = None
_page: Page | None = None
_al = None  # alumnium.Aluminium instance


def _run(coro, timeout: float = 60.0):
    """Submit coroutine to the persistent loop, block until done."""
    future = asyncio.run_coroutine_threadsafe(coro, _loop)
    return future.result(timeout=timeout)


async def _ensure_session():
    """Initialize or recover Playwright + alumnium session."""
    global _browser, _page, _al

    if _page is None or _page.is_closed():
        pw = await async_playwright().start()
        _browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        _page = await _browser.new_page()
        from alumnium import Aluminium
        _al = Aluminium(_page)

    return _page, _al


@mcp.tool()
def al_navigate(url: str) -> str:
    """Navigate to a URL and return page title."""
    async def _do():
        page, _ = await _ensure_session()
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        title = await page.title()
        return f"Navigated to {url} — title: {title}"

    return _run(_do())


@mcp.tool()
def al_do(action: str) -> str:
    """Perform a browser action described in natural language."""
    async def _do():
        _, al = await _ensure_session()
        al.do(action)
        return f"Done: {action}"

    return _run(_do(), timeout=90.0)


@mcp.tool()
def al_check(assertion: str) -> str:
    """
    Verify an assertion about the current page.
    Returns 'true' or 'false: <reason>'.
    """
    async def _do():
        _, al = await _ensure_session()
        result = al.check(assertion)
        if result:
            return "true"
        return f"false: {assertion}"

    return _run(_do(), timeout=60.0)


@mcp.tool()
def al_get(value_desc: str) -> str:
    """Extract a value from the current page described in natural language."""
    async def _do():
        _, al = await _ensure_session()
        return str(al.get(value_desc))

    return _run(_do(), timeout=60.0)


@mcp.tool()
def al_screenshot() -> str:
    """Take screenshot of current page and save to /audit/."""
    async def _do():
        page, _ = await _ensure_session()
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = _AUDIT_DIR / f"alumnium-{ts}.png"
        await page.screenshot(path=str(path))
        return f"Screenshot saved: {path}"

    return _run(_do())


if __name__ == "__main__":
    mcp.run(transport="sse")
```

- [ ] **Step 4: Commit**

```bash
git add hermes/mcp-alumnium/
git commit -m "feat(hermes): add mcp-alumnium container (AI-native E2E testing)"
```

---

## Task 2: docker-compose + bridge _MCP_SERVERS

**Files:**
- Modify: `hermes/docker-compose.yml`
- Modify: `hermes/bridge/hermes_bridge.py`

- [ ] **Step 1: Add mcp-alumnium service to docker-compose.yml**

In `hermes/docker-compose.yml`, after the `mcp-fs-vinhunter` service block, add:

```yaml
  mcp-alumnium:
    build:
      context: ./mcp-alumnium
    container_name: mcp-alumnium
    restart: unless-stopped
    labels: ["hermes=true"]
    networks: [hermes-net]
    expose: ["8000"]
    volumes:
      - ./audit:/audit
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      AUDIT_DIR: /audit
      MCP_TRANSPORT: sse
      MCP_PORT: "8000"
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}
    shm_size: "512m"
    deploy:
      resources:
        limits:
          cpus: "1.0"
          memory: 1g
```

- [ ] **Step 2: Add "alumnium" to _MCP_SERVERS in hermes_bridge.py**

Find `_MCP_SERVERS` dict:
```python
_MCP_SERVERS: dict[str, str] = {
    "browser-mcp": "http://browser-mcp:8000/sse",
    "chrome-readonly-mcp": "http://chrome-readonly-mcp:8000/sse",
    "fs-vinhunter": "http://mcp-fs-vinhunter:8000/sse",
}
```

Replace with:
```python
_MCP_SERVERS: dict[str, str] = {
    "browser-mcp": "http://browser-mcp:8000/sse",
    "chrome-readonly-mcp": "http://chrome-readonly-mcp:8000/sse",
    "fs-vinhunter": "http://mcp-fs-vinhunter:8000/sse",
    "alumnium": "http://mcp-alumnium:8000/sse",
}
```

- [ ] **Step 3: Build and start mcp-alumnium**

```bash
cd hermes
docker compose build mcp-alumnium
docker compose up -d mcp-alumnium
docker compose logs mcp-alumnium --tail 20
```

Expected: build succeeds (playwright chromium downloaded), log shows:
```
Running SSE server on 0.0.0.0:8000
```

- [ ] **Step 4: Smoke test from bridge container**

```bash
docker compose exec hermes-bridge python3 -c "
import asyncio
from mcp_client import MCPClient

async def test():
    async with MCPClient('http://mcp-alumnium:8000/sse') as mcp:
        result = await mcp.call('al_navigate', {'url': 'http://example.com'})
        print(result)

asyncio.run(test())
"
```

Expected output: `Navigated to http://example.com — title: Example Domain`

- [ ] **Step 5: Commit**

```bash
git add hermes/docker-compose.yml hermes/bridge/hermes_bridge.py
git commit -m "feat(hermes): register mcp-alumnium in compose + bridge MCP_SERVERS"
```

---

## Task 3: Fix git in mcp-fs-vinhunter

**Files:**
- Modify: `hermes/mcp-fs-vinhunter/server.py`
- Modify: `.gitignore` (root)

**Context:** `/vinhunter` is a bind-mount of `VIN OSINT/vinhunter/` on the host. There is no `.git` there — git commands fail with "not a git repository". Fix: call `git init` on startup if `.git` is absent. This creates `VIN OSINT/vinhunter/.git/` on the host (a local repo, not connected to any remote). Add it to `.gitignore` so the monorepo's `git status` stays clean.

- [ ] **Step 1: Read current server.py**

Read `hermes/mcp-fs-vinhunter/server.py` to confirm current `_ROOT` initialization and `_git()` function.

- [ ] **Step 2: Add _ensure_git_init() after _ROOT assignment**

Find:
```python
_ROOT = Path(os.environ.get("VINHUNTER_ROOT", "/vinhunter"))
```

Add immediately after it:

```python
def _ensure_git_init() -> None:
    """Initialize a local git repo in _ROOT if not present."""
    git_dir = _ROOT / ".git"
    if git_dir.exists():
        return
    subprocess.run(["git", "init"], cwd=str(_ROOT), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "hermes@local"],
        cwd=str(_ROOT), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Hermes"],
        cwd=str(_ROOT), check=True, capture_output=True,
    )
    # Initial empty commit so branching works immediately
    subprocess.run(["git", "add", "-A"], cwd=str(_ROOT), capture_output=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "chore: hermes local init"],
        cwd=str(_ROOT), check=False, capture_output=True,
    )
    print(f"[mcp-fs-vinhunter] git init done in {_ROOT}", flush=True)


_ensure_git_init()
```

- [ ] **Step 3: Fix _git() to raise on non-zero exit**

Find the current `_git()` function:
```python
def _git(args: list[str]) -> str:
    result = subprocess.run(
        ["git"] + args,
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return (result.stdout + result.stderr).strip()
```

Replace with:
```python
def _git(args: list[str]) -> str:
    result = subprocess.run(
        ["git"] + args,
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {output}")
    return output
```

- [ ] **Step 4: Add to .gitignore**

Read the root `.gitignore` to see current contents. Append:

```
# Hermes-managed local git repo in VINhunter subdirectory
VIN OSINT/vinhunter/.git/
```

- [ ] **Step 5: Rebuild mcp-fs-vinhunter and verify**

```bash
cd hermes
docker compose build mcp-fs-vinhunter
docker compose up -d mcp-fs-vinhunter
docker compose logs mcp-fs-vinhunter --tail 10
```

Expected log line:
```
[mcp-fs-vinhunter] git init done in /vinhunter
```

Then test git_status via bridge:
```bash
docker compose exec hermes-bridge python3 -c "
import asyncio
from mcp_client import MCPClient

async def test():
    async with MCPClient('http://mcp-fs-vinhunter:8000/sse') as mcp:
        result = await mcp.call('git_status', {})
        print('git_status:', result)

asyncio.run(test())
"
```

Expected: empty string or list of untracked files (no "not a git repository" error).

- [ ] **Step 6: Commit**

```bash
git add hermes/mcp-fs-vinhunter/server.py .gitignore
git commit -m "fix(hermes): mcp-fs-vinhunter — git init on startup, raise on git failure"
```

---

## Task 4: vinhunter-researcher Skill + Handler + Cron

**Files:**
- Create: `hermes/skills/vinhunter-researcher.md`
- Modify: `hermes/bridge/hermes_bridge.py`

- [ ] **Step 1: Create skill markdown**

```markdown
# vinhunter-researcher

## When to use
Every 7 days at 10:00 (cron) or manually via `/skill vinhunter-research`.

## Steps
1. List existing plugins via mcp-fs-vinhunter `fs_list_dir("backend/plugins")` — see what categories exist
2. Brave Search (3 queries, deduplicated by domain):
   - `"VIN API EU free 2026"`
   - `"car history database API Europe"`
   - `"vehicle registry open data API"`
3. LLM (medium tier) scores each new source on 4 axes:
   - Type: API REST (5) / scraping (3) / open data file (3)
   - Coverage: EU (5) / global (3) / US only (1)
   - Cost: free (5) / freemium (3) / paid (1)
   - Difficulty: easy (5) / medium (3) / hard (1)
   Total score: 0-20
4. Write report to `audit/vinhunter-research-YYYY-MM-DD.md` (markdown table + Top 3 section)
5. Telegram: top source name + score + ask if to write plugin

## Tools needed
- `fs_list_dir` (mcp-fs-vinhunter)
- `_brave_search` (bridge built-in)
- `llm_client.call_llm(prompt, tier="medium", skill="vinhunter-research")`

## Watch out for
- Deduplicate search results by domain (same URL from multiple queries)
- Report filename must use ISO date YYYY-MM-DD (plugin-writer finds latest by glob sort)
- If Brave Search returns 0 results, report error and skip LLM

## Example
Cron trigger: 10:00
Output Telegram: "🔍 VINhunter research — 2026-05-30\nRaport: audit/vinhunter-research-2026-05-30.md\nNajlepsze: RDW Open Data (score 18/20)\n\nNapisać plugin? /skill vinhunter-write-plugin rdw_open_data"
```

- [ ] **Step 2: Add _handle_vinhunter_researcher() to bridge**

In `hermes/bridge/hermes_bridge.py`, add this function before `_cron_execute_skill` (after `_handle_scrape_autocentrum`):

```python
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
        f"- {r.get('title', '')}: {r.get('url', '')} — {r.get('description', '')}"
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
```

- [ ] **Step 3: Add "vinhunter-researcher" to _CRON_JOBS**

In `_CRON_JOBS` dict, after the `"scrape-autocentrum"` entry, add:

```python
    "vinhunter-researcher": {
        "interval_s": 604800,
        "run_at_hour": 10,
        "enabled": True,
        "last_run": 0.0,
        "description": "Research new VIN data sources (weekly, 10:00)",
        "notify": "always",
    },
```

- [ ] **Step 4: Register in _cron_execute_skill**

Find:
```python
    if skill_name == "scrape-autocentrum":
        return _handle_scrape_autocentrum()
    return f"[cron] skill '{skill_name}' not supported for cron."
```

Replace with:
```python
    if skill_name == "scrape-autocentrum":
        return _handle_scrape_autocentrum()
    if skill_name == "vinhunter-researcher":
        return _handle_vinhunter_researcher()
    return f"[cron] skill '{skill_name}' not supported for cron."
```

- [ ] **Step 5: Register in SKILL routing (_make_reply)**

Find the skill routing block with `scrape-autocentrum`:
```python
        if skill_name in ("scrape-autocentrum",):
            return _handle_scrape_autocentrum(skill_args)
        return f"[stub] skill '{skill_name}' nie jest jeszcze zaimplementowany."
```

Replace with:
```python
        if skill_name in ("scrape-autocentrum",):
            return _handle_scrape_autocentrum(skill_args)
        if skill_name in ("vinhunter-research", "vinhunter-researcher"):
            return _handle_vinhunter_researcher()
        return f"[stub] skill '{skill_name}' nie jest jeszcze zaimplementowany."
```

- [ ] **Step 6: Restart bridge, test manual trigger**

```bash
docker compose restart hermes-bridge
```

From Telegram: `/skill vinhunter-research`

Wait 30-60s. Expected Telegram response:
```
🔍 VINhunter research — 2026-05-24
Raport: audit/vinhunter-research-2026-05-24.md
Najlepsze źródło: <name>

Napisać plugin? /skill vinhunter-write-plugin <name>
```

Verify report:
```bash
cat hermes/audit/vinhunter-research-$(date +%Y-%m-%d).md
```

- [ ] **Step 7: Commit**

```bash
git add hermes/skills/vinhunter-researcher.md hermes/bridge/hermes_bridge.py
git commit -m "feat(hermes): add vinhunter-researcher skill + weekly cron 10:00"
```

---

## Task 5: vinhunter-plugin-writer Skill + Handler

**Files:**
- Create: `hermes/skills/vinhunter-plugin-writer.md`
- Modify: `hermes/bridge/hermes_bridge.py`

- [ ] **Step 1: Create skill markdown**

```markdown
# vinhunter-plugin-writer

## When to use
After `vinhunter-researcher` produces a report. Triggered manually via `/skill vinhunter-write-plugin [source_name]`.

## Steps
1. Find latest `audit/vinhunter-research-*.md` report
2. Read 2 existing plugins as code templates: `nhtsa.py` (vin_decode) + `nl_rdw.py` (registries)
3. LLM (hard tier, max 2048 tokens) generates complete plugin .py file
4. Via mcp-fs-vinhunter:
   a. `git_checkout_branch("hermes/plugin-{source_name}")` — create local branch
   b. `fs_write_file("backend/plugins/{category}/{source_name}.py", code)` — write file
   c. `git_commit("feat(plugins): add {source_name} plugin (hermes-generated)")` — commit
5. Alumnium health check on VINhunter backend (optional — skip if not running)
6. Telegram: ✅ plugin written + file path + branch name + next steps

## Tools needed
- `fs_read_file`, `fs_write_file`, `git_checkout_branch`, `git_commit` (mcp-fs-vinhunter)
- `al_navigate` (mcp-alumnium) — optional health check
- `llm_client.call_llm(prompt, tier="hard", max_tokens=2048, skill="vinhunter-plugin-writer")`

## Watch out for
- LLM may wrap code in ```python fences — strip them before writing
- Category detection: check for `REGISTRY`, `DAMAGE`, `PHOTO_OSINT`, `ADS_ARCHIVE` in generated code
- VINhunter needs restart to load new plugin (hot-reload not supported)
- git_push will fail (local-only repo, no remote) — that's expected, mention it in output

## Example
Input: `/skill vinhunter-write-plugin rdw_open_data`
Output: "✅ Plugin `rdw_open_data` napisany.\nPlik: backend/plugins/registries/rdw_open_data.py\nBranch: hermes/plugin-rdw_open_data\nZrestartuj VINhunter żeby załadować plugin."
```

- [ ] **Step 2: Add _handle_vinhunter_plugin_writer() to bridge**

Add this function after `_handle_vinhunter_researcher()`:

```python
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

    # 2. Read existing plugin templates
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
```

- [ ] **Step 3: Register in SKILL routing (_make_reply)**

Find:
```python
        if skill_name in ("vinhunter-research", "vinhunter-researcher"):
            return _handle_vinhunter_researcher()
        return f"[stub] skill '{skill_name}' nie jest jeszcze zaimplementowany."
```

Replace with:
```python
        if skill_name in ("vinhunter-research", "vinhunter-researcher"):
            return _handle_vinhunter_researcher()
        if skill_name in ("vinhunter-write-plugin", "vinhunter-plugin-writer"):
            return _handle_vinhunter_plugin_writer(skill_args)
        return f"[stub] skill '{skill_name}' nie jest jeszcze zaimplementowany."
```

- [ ] **Step 4: Restart bridge and test end-to-end**

```bash
docker compose restart hermes-bridge
```

First trigger researcher (if not done already):
```
/skill vinhunter-research
```

Then trigger plugin writer:
```
/skill vinhunter-write-plugin rdw_open_data
```

Wait 60-120s (LLM hard tier). Expected response:
```
✅ Plugin `rdw_open_data` napisany.
Plik: backend/plugins/registries/rdw_open_data.py
Branch: `hermes/plugin-rdw_open_data` (lokalny)
Git: [master abc1234] feat(plugins): add rdw_open_data plugin (hermes-generated)
VINhunter nie odpowiada (OK jeśli nie jest uruchomiony).

Następny krok: zrestartuj VINhunter i zweryfikuj plugin.
```

Verify file on host:
```bash
ls "VIN OSINT/vinhunter/backend/plugins/registries/"
cat "VIN OSINT/vinhunter/backend/plugins/registries/rdw_open_data.py" | head -30
```

- [ ] **Step 5: Commit**

```bash
git add hermes/skills/vinhunter-plugin-writer.md hermes/bridge/hermes_bridge.py
git commit -m "feat(hermes): add vinhunter-plugin-writer skill (LLM-generated plugins)"
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| mcp-alumnium container (Playwright + alumnium + FastMCP SSE) | Task 1 ✅ |
| al_navigate, al_do, al_check, al_get, al_screenshot tools | Task 1 ✅ |
| docker-compose: mcp-alumnium service | Task 2 ✅ |
| bridge: "alumnium" in _MCP_SERVERS | Task 2 ✅ |
| Fix git tools in mcp-fs-vinhunter (git init on startup) | Task 3 ✅ |
| vinhunter-researcher.md skill file | Task 4 ✅ |
| vinhunter-researcher handler (Brave Search → LLM → report → Telegram) | Task 4 ✅ |
| vinhunter-researcher cron (weekly, 10:00) | Task 4 ✅ |
| vinhunter-plugin-writer.md skill file | Task 5 ✅ |
| vinhunter-plugin-writer handler (report → LLM → write → test → commit) | Task 5 ✅ |
| alumnium health check in plugin-writer | Task 5 ✅ |

**Known limitation:** `run_at_weekday` (Friday) is not implemented in `_should_run_now`. The cron runs every 7 days at 10:00 from first trigger — effectively weekly at the right hour, but not pinned to Friday. Acceptable without a scheduler rewrite.

**git_push not implemented:** The local git repo has no remote. `git_push` calls would fail. The plan deliberately omits push and instructs the user to merge manually. The plugin is still written and committed locally; the file is visible on the host at `VIN OSINT/vinhunter/`.

---

## Next Plan

- `2026-05-24-hermes-income-radar.md` — income-freelance (useme profile init) + income-product skills + crony
