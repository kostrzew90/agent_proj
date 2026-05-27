# Project Digest — Hermes skill (design)

**Data**: 2026-05-27
**Autor**: brainstorm Damian + Claude
**Status**: draft (przed implementacją)

## 1. Cel

Hermes wysyła automatyczne podsumowanie projektów dwa razy dziennie na Telegram:
- **rano 8:00 UTC** — co mnie czeka (koszty wczoraj, queue, health)
- **wieczorem 20:00 UTC** — co zrobiono (commity, koszty, highlights z review-learn, research)

Cel: operational awareness lokalnego AI stacka (RAG, Selfmadeagent, VINhunter, trading-app, hermes) bez ręcznego sprawdzania logów.

## 1a. Threat model (przed architekturą — must read)

**Telegram = external boundary.** Wszystko co trafia do digestu traktować jak "opuszcza system": cloud storage, mobile, notifications, screenshots, forwarding. Z tego wynikają twarde reguły:

1. **Sanitizer secrets** wołany na końcu `_format_digest()` przed returnem (MUST HAVE).
2. **Extras** — allowlist `*.log`/`*.jsonl` + denylist (`auth.log`, `secrets.json`, `.env`, `cdp*.log` z Chrome).
3. **Research/agent logs** — tylko metadata (count, temat), nigdy raw prompts/RAG context.
4. **Endpointy HTTP health** — hardcoded, nigdy z configu/usera bez allowlist hostów.
5. **PROJECTS map** — static dict, nigdy ścieżki z Telegrama (path traversal).
6. **Docker.sock awareness**: Hermes ma `/var/run/docker.sock` = root host. Compromise Hermesa = compromise hosta. Spec nie rozwiązuje tego (out of scope: sidecar/RO socket), ale dokumentuje świadomie.
7. **Subprocess** — wyłącznie listy argumentów, brak `shell=True`, `assert isinstance(hours, int)`.

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
    assert isinstance(hours, int), "hours must be int (subprocess safety)"
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

**Shortstat parser** — best-effort: merge commits, multiline stats i binary files mogą zwrócić nietypowe linie. Wrapper:
```python
def _parse_git_log(stdout: str) -> dict:
    commits = []
    files_changed = 0
    for line in stdout.splitlines():
        try:
            if re.match(r"^[a-f0-9]{7,} ", line):
                commits.append(line)
            elif " file" in line and " changed" in line:
                m = re.search(r"(\d+) files? changed", line)
                if m:
                    files_changed += int(m.group(1))
        except Exception:
            continue  # best-effort, never crash whole digest
    return {"commits": commits, "files_changed": files_changed}
```

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

    # Tail-only read (cap CPU+RAM on large files — iterator-based, NOT read_text)
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        lines = collections.deque(f, maxlen=5000)

    MAX_LINE = 16384  # 16KB cap — memory bomb protection
    for line in lines:
        if len(line) > MAX_LINE:
            continue
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
- cap `maxlen=5000` linii (iterator deque, nie `read_text().splitlines()` — realny tail-only)
- max line length 16KB — chroni przed pojedynczą gigantyczną linią (memory bomb)

**Furtka na potem**: jeśli pliki przekroczą 5000 linii dziennie, zamienić na byte-offset checkpoint w `digest-state.json` (jak `review-learn` z `reviewed.json`).

### 4.4 `_health_check()` — rozdzielone

```python
def _health_check() -> dict:
    containers: dict[str, str] = {}
    try:
        # -a → exited/crashed widoczne, nie tylko UP
        r = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}"],
            timeout=5, capture_output=True, text=True,
        )
        for line in r.stdout.splitlines():
            name, _, status = line.partition("\t")
            if status.startswith("Up"):
                containers[name] = "up"
            elif status.startswith("Exited"):
                containers[name] = "exited"
            elif status.startswith("Restarting"):
                containers[name] = "restarting"
            else:
                containers[name] = "unknown"
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
ALLOW_PATTERNS = ("*.log", "*.jsonl")
DENY_FILES = {
    "auth.log", "secrets.json", ".env",
    "cdp.log", "cdp_readonly.log",  # Chrome — cookies/tokens
    "costs.jsonl", "review-learn.log", "cron.log",
    "research.log", "watcher-heartbeat.txt",  # already covered
    "llm-proxy.jsonl",  # raw prompts/responses
}

def _scan_extras(since_hours: int) -> list[dict]:
    cutoff = time.time() - since_hours * 3600
    extras: list[dict] = []

    candidates = set()
    for pat in ALLOW_PATTERNS:
        candidates.update(Path("/audit").glob(pat))

    for path in sorted(candidates):
        if path.name in DENY_FILES or not path.is_file():
            continue
        if path.stat().st_mtime < cutoff:
            continue
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                tail = collections.deque(f, maxlen=1)
            if not tail:
                continue
            line = tail[-1].strip()
            if len(line) > 16384:
                continue  # memory bomb cap

            # JSONL: parse and pull message/event/type for readable output
            display = line[:180]
            if path.suffix == ".jsonl":
                try:
                    obj = json.loads(line)
                    for key in ("message", "event", "type", "msg", "summary"):
                        if key in obj:
                            display = f"{key}={obj[key]}"[:180]
                            break
                except (json.JSONDecodeError, ValueError):
                    pass
        except Exception:
            continue
        extras.append({"file": path.name, "last": display})
        if len(extras) >= 10:
            break

    return extras
```

**Reguły**:
- **allowlist patterns** (`*.log`, `*.jsonl`) zamiast `glob("*")`
- **denylist** (auth, secrets, .env, cdp*, llm-proxy.jsonl — raw prompts) — security boundary
- max 10 extras, max 1 entry/plik, truncate 180 chars
- JSONL → pretty extract `message`/`event`/`type`, fallback raw
- max line length 16KB (memory bomb)

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

Buduje string ≤3800 chars. Telegram limit 4096, rezerwa na nagłówek i `📂 pełny digest: ścieżka`.

**Graceful section truncation** zamiast brutalnego `[:3800]`:
```python
def _append_section_if_space(lines: list[str], section: list[str], budget: int) -> int:
    """Append section if it fits; else truncate with '… (+N more)' marker."""
    section_size = sum(len(s) + 1 for s in section)
    if section_size <= budget:
        lines.extend(section)
        return budget - section_size
    # Partial fit
    used = 0
    for i, s in enumerate(section):
        if used + len(s) + 1 > budget - 30:  # reserve for marker
            lines.append(f"… (+{len(section) - i} more)")
            return 0
        lines.append(s)
        used += len(s) + 1
    return budget - used
```

**Sanitizer (MUST HAVE — wołany na końcu przed return)**:
```python
_SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_-]{16,}"), "sk-***REDACTED***"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._-]{16,}", re.I), "Bearer ***REDACTED***"),
    (re.compile(r"(api[_-]?key|token|secret)\s*[=:]\s*[^\s,;]+", re.I), r"\1=***REDACTED***"),
    (re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"), "***JWT-REDACTED***"),
    (re.compile(r"\b[a-f0-9]{40,}\b"), "***HEX-REDACTED***"),
    (re.compile(r"OPENAI_API_KEY|ANTHROPIC_API_KEY|GROQ_API_KEY"), r"***ENV-VAR***"),
]

def _sanitize(text: str) -> str:
    for pat, repl in _SECRET_PATTERNS:
        text = pat.sub(repl, text)
    return text

# Use at end of _format_digest:
return _sanitize("\n".join(lines))
```

**Sekcja `signals: []` zawsze obecna** — pusta lista teraz, na przyszłość. W v2: detekcja `cost_increase_pct > 50`, `commits_48h == 0`, `failed_health_checks > 0`, `extras_growth > 100`.

## 5. Lockfile

Implementacja singleton execution z atomic reclaim:

```python
@contextmanager
def _digest_lock(name: str):
    lock_path = Path(f"/audit/.digest-{name}.lock")
    # O_NOFOLLOW chroni przed symlink attack jeśli /audit byłby writable przez inny proces
    flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    def _acquire() -> int | None:
        try:
            fd = os.open(str(lock_path), flags, 0o600)
            os.write(fd, str(os.getpid()).encode())
            return fd
        except FileExistsError:
            return None

    fd = _acquire()
    if fd is None:
        # Stale check
        try:
            stale_pid = int(lock_path.read_text())
            os.kill(stale_pid, 0)  # alive? raises if dead
            yield False  # locked by alive process, skip
            return
        except (ProcessLookupError, ValueError):
            # Stale — unlink and retry atomically (closes race window)
            lock_path.unlink(missing_ok=True)
            fd = _acquire()
            if fd is None:
                # Someone else won the race after our unlink
                yield False
                return

    try:
        yield True
    finally:
        os.close(fd)
        lock_path.unlink(missing_ok=True)
```

Zmiany vs poprzedni draft:
- **Atomic reclaim**: po `unlink` stale → ponowny `os.open(O_EXCL)`. Jeśli ktoś nas wyprzedzi → `yield False`.
- **`O_NOFOLLOW`**: symlink na `.lock` nie zostanie zaakceptowany (Linux/Mac).
- **`0o600`**: lockfile readable tylko przez właściciela.

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
- **Docker.sock hardening** — sidecar / RO socket / docker-events proxy. Świadomie zostawione — compromise Hermesa = compromise hosta, ale ten ryzyko istnieje już w obecnym setupie i nie jest wprowadzane przez ten skill
- **Signed audit entries, tamper detection, RBAC, encrypted digest storage** — out, single-user lokalny setup

## 9. Akceptowane guardrails

### Z brainstormu pierwotnego
✅ #1 git timeout + cwd validation + soft fail
✅ #2 partial JSONL — ignore malformed, validate fields
✅ #3 health check rozdzielony container vs HTTP
✅ #4 extras gate: max 10, 1 entry/plik, 180 chars
✅ #5 morning queue: `new_last_24h` + `pending`
✅ #6 evening highlights TOP 2
✅ #7 lockfile / singleton execution
✅ #8 sekcja `signals: []` zarezerwowana
✅ #10 timezone explicit UTC
✅ #11 tryb wyciągany ze skill_name, nie godziny
✅ #13 cap na rozmiar parsowanych logów (deque maxlen=5000)

### Z review specu (technical)
✅ R1 Lock atomic reclaim (retry `os.open` po stale cleanup) — sekcja 5
✅ R2 `open() + deque(f)` tail-only — sekcja 4.3
✅ R3 `docker ps -a` — sekcja 4.4
✅ R4 JSONL parse w extras (`message`/`event`/`type`) — sekcja 4.5
✅ R5 shortstat best-effort parser — sekcja 4.2
✅ R6 graceful section truncation — sekcja 4.9

### Z review specu (security)
✅ S1 `assert isinstance(hours, int)` — sekcja 4.2
✅ S2 **Sanitizer secrets** (sk-, Bearer, api_key=, JWT, hex≥40, env-var names) — sekcja 4.9
✅ S3 Extras allowlist + denylist (auth.log, secrets.json, .env, cdp*, llm-proxy.jsonl) — sekcja 4.5
✅ S4 Docker.sock awareness — sekcje 1a + 8
✅ S5 SSRF — endpointy hardcoded, dokumentacja w 1a
✅ S6 Path traversal — PROJECTS static, dokumentacja w 1a
✅ S7 `O_NOFOLLOW` na lockfile + `0o600` perms — sekcja 5
✅ S8 Max line length 16KB w JSONL parsing — sekcje 4.3, 4.5
✅ S9 Research logs → tylko metadata — sekcja 4.8 + 1a (zasada)
✅ S10 Telegram = external boundary — sekcja 1a (mental model)

### Odrzucone z pierwotnego brainstormu
- #9 manualny tryb z mode-arg — skill_name wystarczy
- #12 empty-state always send — nie must-have, do v2
