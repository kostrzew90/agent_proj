# Project Digest — Hermes skill (design)

**Data**: 2026-05-27
**Autor**: brainstorm Damian + Claude
**Status**: draft (przed implementacją)

## 1. Cel

Hermes wysyła automatyczne podsumowanie projektów dwa razy dziennie na Telegram:
- **rano 8:00 UTC** — co mnie czeka (koszty wczoraj, queue, health)
- **wieczorem 20:00 UTC** — co zrobiono (commity, koszty, highlights z review-learn, research)

Cel: operational awareness lokalnego AI stacka (RAG, Selfmadeagent, VINhunter, trading-app, hermes) bez ręcznego sprawdzania logów.

## 2. Architektura

### 2.1 Pliki

| Plik | Zmiana |
|------|--------|
| `hermes/skills/project-digest.md` | nowy skill (dokumentacja) |
| `hermes/bridge/hermes_bridge.py` | +2 wpisy w `_CRONS`, +`_handle_project_digest(mode)`, +helpery |
| `hermes/audit/digest-state.json` | persistent state (offsety, last_run) — tworzony przez handler |

### 2.2 Crony

```python
"project-digest-morning": {
    "interval_s": 86400, "run_at_hour": 8, "enabled": True,
    "description": "Project digest (morning, 8:00 UTC)",
    "notify": "always",
},
"project-digest-evening": {
    "interval_s": 86400, "run_at_hour": 20, "enabled": True,
    "description": "Project digest (evening, 20:00 UTC)",
    "notify": "always",
},
```

Oba routują do `_handle_project_digest(skill_name)`. **Tryb wyciągany ze skill_name** (`-morning`/`-evening`), nie z aktualnej godziny — odporne na opóźnienie crona przez lock/network.

### 2.3 Strefa czasowa

Wszystkie cutoffs (12h, 24h) liczone od `time.time()` (UTC). `run_at_hour: 8` interpretowane jako UTC. 8 UTC ≈ 10:00 CEST latem, 9:00 CET zimą. Spec celowo trzyma się UTC żeby uniknąć dryfu DST.

## 3. Zawartość digestu

### 3.1 Morning (8:00 UTC) — "co mnie czeka"

```
🌅 Project Digest — Morning (2026-05-27)

💰 Costs (last 24h)
  Total: $X.XX
  gpt-5: $X.XX
  claude-sonnet: $X.XX
  (etries: N)

📊 Health
  Containers:
    🟢 rag-backend, rag-postgres, selfmadeagent, hermes
    🔴 hermes-watcher (down)
  HTTP:
    🟢 RAG /health (45ms)
    🔴 Selfmadeagent /health (timeout)

🔍 Review-learn queue
  new last 24h: 8
  pending: 23 (next: backend/core/retriever.py)

📋 Extras
  [autocentrum_queue.json] 12 pending
```

### 3.2 Evening (20:00 UTC) — "co zrobiono"

```
🌙 Project Digest — Evening (2026-05-27)

💰 Costs (today)
  Total: $X.XX
  (per model jak wyżej)

📦 Git activity (last 12h)
  RAG: 3 commits, 8 files
    🔝 feat(rag): wire reranker into chat_service
    🔝 fix(rag): close http clients in lifespan
  Selfmadeagent: 1 commit, 2 files
  VINhunter: 0
  trading-app: 0
  hermes: 2 commits, 4 files

🎯 Review-learn highlights (TOP 2)
  • llm_reranker.py — resource leak, missing close()
  • chat_service.py — hidden invariant in index_map

🔬 Research (last 12h)
  3 entries, ostatni: "agentic patterns RRF hybrid"

📋 Extras
  [research.log] 12 nowych wpisów
  [ingest.log] 47 docs processed

🚨 Signals (future)
  (sekcja zarezerwowana — anomaly detection v2)
```

## 4. Handlery i helpery

### 4.1 `_handle_project_digest(skill_name: str) -> str`

```python
def _handle_project_digest(skill_name: str) -> str:
    mode = "morning" if "morning" in skill_name else "evening"
    cutoff_h = 24 if mode == "morning" else 12

    data = {
        "costs": _parse_costs(since_hours=cutoff_h),
        "health": _health_check(),
    }
    if mode == "morning":
        data["queue"] = _review_learn_queue()
    else:
        data["git"] = _git_log_since(hours=12)
        data["highlights"] = _review_learn_highlights(last_n=2)
        data["research"] = _research_log_since(hours=12)

    data["extras"] = _scan_extras(since_hours=cutoff_h)
    return _format_digest(mode, data)
```

### 4.2 `_git_log_since(hours)` — guardrail

```python
PROJECTS = {
    "RAG": "/workspace/ro/RAG",
    "Selfmadeagent": "/workspace/ro/Selfmadeagent",
    "VINhunter": "/workspace/ro/VIN OSINT/vinhunter",
    "trading-app": "/workspace/ro/trading-app",
    "hermes": "/workspace/ro/hermes",
}

def _git_log_since(hours: int) -> dict:
    out = {}
    for name, path in PROJECTS.items():
        if not Path(path).exists():
            out[name] = {"error": "repo missing"}
            continue
        try:
            r = subprocess.run(
                ["git", "log", f"--since={hours} hours ago",
                 "--pretty=format:%h %s", "--shortstat"],
                cwd=path, timeout=10, capture_output=True, text=True,
            )
            if r.returncode != 0:
                out[name] = {"error": "git error"}
                continue
            out[name] = _parse_git_log(r.stdout)
        except subprocess.TimeoutExpired:
            out[name] = {"error": "timeout"}
        except Exception as exc:
            out[name] = {"error": str(exc)[:60]}
    return out
```

**Soft fail**: jeden uszkodzony repo → wpis `⚠️ trading: repo unavailable`, reszta digestu działa.

### 4.3 `_parse_costs(since_hours)` — odporność na partial JSONL

```python
def _parse_costs(since_hours: int) -> dict:
    cutoff = time.time() - since_hours * 3600
    by_model: dict[str, float] = {}
    total = 0.0
    entries = 0

    path = Path("/audit/costs.jsonl")
    if not path.exists():
        return {"total_usd": 0.0, "by_model": {}, "entries": 0}

    # Tail-only read (cap CPU on large files)
    lines = collections.deque(
        path.read_text(encoding="utf-8", errors="ignore").splitlines(),
        maxlen=5000,
    )
    for line in lines:
        try:
            e = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        ts = e.get("timestamp") or e.get("ts")
        if not ts or _to_epoch(ts) < cutoff:
            continue
        model = e.get("model", "unknown")
        cost = float(e.get("cost_usd", 0) or 0)
        by_model[model] = by_model.get(model, 0) + cost
        total += cost
        entries += 1

    return {"total_usd": total, "by_model": by_model, "entries": entries}
```

**Guardrails**:
- malformed JSON line → ignore (nie crashuj)
- brakujące pola → defaulty
- cap `maxlen=5000` linii — gdy `costs.jsonl` urośnie

**Furtka na potem**: jeśli pliki przekroczą 5000 linii dziennie, zamienić na byte-offset checkpoint w `digest-state.json` (jak `review-learn` z `reviewed.json`).

### 4.4 `_health_check()` — rozdzielone

```python
def _health_check() -> dict:
    containers: dict[str, bool] = {}
    try:
        r = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
            timeout=5, capture_output=True, text=True,
        )
        for line in r.stdout.splitlines():
            name, _, status = line.partition("\t")
            containers[name] = status.startswith("Up")
    except Exception:
        containers = {"_error": False}

    http: dict[str, dict] = {}
    endpoints = {
        "RAG": "http://rag-backend:8000/health",
        "Selfmadeagent": "http://selfmadeagent:8080/health",
    }
    for name, url in endpoints.items():
        t0 = time.monotonic()
        try:
            resp = requests.get(url, timeout=3)
            http[name] = {
                "ok": resp.status_code == 200,
                "latency_ms": int((time.monotonic() - t0) * 1000),
            }
        except Exception as exc:
            http[name] = {"ok": False, "error": str(exc)[:40]}

    return {"containers": containers, "http": http}
```

Container UP ale endpoint DEAD — widoczne osobno.

### 4.5 `_scan_extras(since_hours)` — gate

```python
def _scan_extras(since_hours: int) -> list[dict]:
    KNOWN = {"costs.jsonl", "review-learn.log", "cron.log",
             "research.log", "watcher-heartbeat.txt"}
    cutoff = time.time() - since_hours * 3600
    extras = []

    for path in Path("/audit").glob("*"):
        if path.name in KNOWN or not path.is_file():
            continue
        if path.stat().st_mtime < cutoff:
            continue
        try:
            tail = collections.deque(
                path.read_text(encoding="utf-8", errors="ignore").splitlines(),
                maxlen=1,
            )
            last = tail[-1][:180] if tail else "(empty)"
        except Exception:
            continue
        extras.append({"file": path.name, "last": last})
        if len(extras) >= 10:
            break

    return extras
```

**Reguły**:
- max 10 extras
- max 1 entry per plik
- truncate 180 chars
- nie pokazuj plików obsługiwanych przez inne sekcje (KNOWN set)

### 4.6 `_review_learn_highlights(last_n)`

Czyta `audit/review-learn.log` (JSONL), bierze ostatnie N entries z dzisiaj, wyciąga pierwszy bullet z preview każdego review. Skraca do 80 chars.

### 4.7 `_review_learn_queue()`

Liczy:
- `new_last_24h` — entries w `review-learn.log` od `now-24h`
- `pending` — wszystkie pliki `.py` w projektach minus `review-learn-reviewed.json` (set difference)
- `next` — pierwszy plik z różnicy zbiorów

### 4.8 `_research_log_since(hours)`

`audit/research.log` — count entries + ostatni temat.

### 4.9 `_format_digest(mode, data)`

Buduje string ≤3800 chars. Telegram limit 4096, ale rezerwa na nagłówek i `📂 pełny digest: ścieżka` line.

**Sekcja `signals: []` zawsze obecna** — pusta lista teraz, na przyszłość. W v2: detekcja `cost_increase_pct > 50`, `commits_48h == 0`, `failed_health_checks > 0`, `extras_growth > 100`.

## 5. Lockfile

Implementacja singleton execution (Twój punkt #7):

```python
@contextmanager
def _digest_lock(name: str):
    lock_path = Path(f"/audit/.digest-{name}.lock")
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
        os.write(fd, str(os.getpid()).encode())
        try:
            yield True
        finally:
            os.close(fd)
            lock_path.unlink(missing_ok=True)
    except FileExistsError:
        # Stale lock? Check PID
        try:
            stale_pid = int(lock_path.read_text())
            os.kill(stale_pid, 0)  # alive? raises if dead
            yield False  # locked, skip
        except (ProcessLookupError, ValueError):
            lock_path.unlink(missing_ok=True)
            yield True  # stale → claim
```

Handler na początku:
```python
with _digest_lock(skill_name) as acquired:
    if not acquired:
        return f"digest {skill_name} already running, skipping"
    # ... reszta
```

Chroni przed double-fire gdy 8:00 cron jeszcze wisi w network calls a 8:01 scheduler odpala drugi raz.

## 6. Persistence — `audit/digest-state.json`

```json
{
  "morning": {"last_run_ts": 1748332800, "last_total_usd": 2.41},
  "evening": {"last_run_ts": 1748376000, "last_total_usd": 4.12}
}
```

Używane teraz tylko do trendów ("wczoraj $2.41, dziś $X"). Furtka na byte-offset checkpoints dla logów (4.3) — jak będzie potrzeba, dorzucimy field `cost_jsonl_offset`.

## 7. Testowanie

**Manualny test przez Telegram**: użytkownik wysyła do bota `/skill project-digest-morning` lub `/skill project-digest-evening`. Router w `hermes_bridge.py` (sekcja koło linii 2935) dostaje nowy wpis routujący.

**Health-check projektów**: po implementacji odpalić oba tryby ręcznie, sprawdzić że żadna soft-failure nie blokuje reszty digestu. Symulować: zatrzymać RAG container, usunąć tymczasowo katalog projektu, popsuć JSONL.

## 8. Out of scope (v2)

- Signals/anomaly detection (sekcja zarezerwowana w outputcie)
- LLM-generated summary (np. "co Hermes uważa za najważniejsze dziś")
- Byte-offset checkpointing dla logów (gdy `costs.jsonl` > 5000 linii)
- Per-projekt opt-out (gdyby user chciał wyłączyć digest dla trading-app)
- Tryb manualny `/skill project-digest morning` (override godziny) — odpada, route przez skill_name wystarczy

## 9. Akceptowane guardrails (z brainstormu)

✅ #1 git timeout + cwd validation + soft fail
✅ #2 partial JSONL — ignore malformed, validate fields
✅ #3 health check rozdzielony container vs HTTP
✅ #4 extras gate: max 10, 1 entry/plik, 180 chars
✅ #5 morning queue: `new_last_24h` + `pending` zamiast totalnego count
✅ #6 evening highlights TOP 2 (TOP 3 commits, TOP errors — w `signals` v2)
✅ #7 lockfile / singleton execution
✅ #8 sekcja `signals: []` zarezerwowana
✅ #10 timezone explicit UTC
✅ #11 tryb wyciągany ze skill_name, nie godziny
✅ #13 cap na rozmiar parsowanych logów (deque maxlen=5000)

Odrzucone: #9 (manualny tryb — zbędne, skill_name wystarczy), #12 (empty-state always send — nie dyskutowane jako must-have).
