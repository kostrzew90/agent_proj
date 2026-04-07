# Design: Transcription Fix + X Post Ingestion + llm-proxy MCP
**Date:** 2026-04-07  
**Project:** RAG Pipeline (`RAG/`)  
**Status:** Approved

---

## 1. Problem Summary

Three independent improvements:

1. **Transcription hang** — uploaded MP3 (2h10m) was killed by OOM after Groq hit rate limit and fell back to local `tiny` whisper on full file.
2. **X Post ingestion** — endpoint exists (`ingestion/xpost.py`) but untested; FxTwitter cascade needs smoke test and Celery task wiring.
3. **llm-proxy MCP** — `ask_ollama` missing; existing `ask_gemini`/`ask_openrouter` use blocking `requests`; MCP may not start due to missing packages.

---

## 2. Transcription Fix

### Root Cause (diagnosed)

```
Groq chunk 1/3 ✅  (2614s used)
Groq chunk 2/3 ✅  (2614s used, total 5228s of 7200s/hr)
Groq chunk 3/3 ❌  HTTP 429 — only 1972s remaining, needed 2614s
Fallback: local faster-whisper tiny, full 2h10m file
SIGKILL (OOM) after 2 min — container memory exhausted
```

### Fix: `RAG/backend/ingestion/transcriber.py`

**Groq rate limit handling:**
- On HTTP 429, parse `Retry-After` header if present
- Fallback default: 300s if `Retry-After` header is missing
- Sleep and retry the same chunk, up to 3 attempts
- Only fall back to local after 3 failed retries

**Local fallback — VAD-based chunked processing:**

Pipeline:
```
audio → ffmpeg silencedetect → silence timestamps
      → group into 5-10 min chunks (split at silence gaps)
      → for each chunk: ffmpeg extract (+ 10s overlap) → faster-whisper → segments + offset
      → dedup overlap regions → merge all segments → full transcript
```

Key decisions:
- **ffmpeg `silencedetect`** for finding split points — no extra Python dependency; faster-whisper already bundles silero-vad internally for `vad_filter=True`, but we need silence points *before* splitting, not during transcription
- **Chunk size**: 5-10 min target — keeps RAM low, faster retry on failure
- **Overlap**: 10s on each chunk boundary — prevents cut-off words at split points
- **Overlap dedup**: after transcribing chunk N+1, discard any segments whose `start` timestamp (absolute) falls before the `end` timestamp of the last segment from chunk N. This eliminates duplicate text from overlap regions.
- **Split at silence**: `silencedetect` finds pauses ≥0.5s → pick the silence gap closest to target chunk boundary → no mid-sentence cuts → better quality
- `vad_filter=True` in faster-whisper call — let Whisper's internal silero-vad skip silence within each chunk for speed
- Prevents OOM: model stays loaded (~1.5 GB RAM), only one 5-10 min chunk in memory at a time

**WHISPER_THREADS integration:**
```python
_model = WhisperModel(
    _model_size,
    device="cpu",
    compute_type="int8",
    cpu_threads=int(os.environ.get("WHISPER_THREADS", "4")),
)
```

**Torch dependency note:** `silero-vad` is NOT needed as a separate package. faster-whisper uses silero-vad internally (via `vad_filter=True`). For chunk splitting we use ffmpeg `silencedetect` which has zero Python dependencies. Torch is already in the Docker image via Docling, but the transcriber pipeline does not depend on it directly.

**Model: `large-v3-turbo`**
- Distilled from large-v3: same encoder (1500M params), 4 decoder layers instead of 32
- ~8x faster than large-v3 on CPU, near-identical quality
- Replaces `tiny` (which was set via env var)

**Environment variables (in `docker-compose-app.yml`, services `rag-api` + `rag-worker`):**
```yaml
WHISPER_MODEL_SIZE: large-v3-turbo
WHISPER_THREADS: "6"
```

**Ollama env vars (Windows system environment, not Docker):**
```
OLLAMA_NUM_PARALLEL=1
OLLAMA_MAX_LOADED_MODELS=1
```
Set via Windows System Properties → Environment Variables → System variables. Requires Ollama service restart.

### Stuck document recovery

The file "Jak budować narzędzia z Claude Code.mp3" is stuck with `status='processing'` after OOM kill. Two-part fix:

1. **Add reprocess endpoint**: `POST /api/v1/documents/{id}/reprocess` — resets document status to `pending`, clears existing chunks, dispatches new `process_document` Celery task. Auth required, only document owner or admin.
2. **One-time SQL fix** (for already-stuck documents):
   ```sql
   UPDATE documents SET status = 'pending', processing_error = NULL
   WHERE status = 'processing'
     AND updated_at < NOW() - INTERVAL '1 hour';
   ```

### Expected outcome for 2h10m file
- Groq processes chunks 1+2 → hits rate limit on chunk 3 → waits ~4.5 min (or 300s default) → retries chunk 3 → success
- If Groq unavailable: ~26 × 5-min chunks × ~1.5 min each ≈ ~40 min total (large-v3-turbo CPU, same total time but smaller memory footprint and better quality at boundaries)

---

## 3. X Post Ingestion

### Architecture

```
POST /api/v1/documents/ingest-xpost
  body: { "url": "https://x.com/username/status/123456" }
  auth: JWT required

→ validate URL (regex: x.com|twitter.com/*/status/*)
→ xpost_ingest_task.delay(url, user_id)   [Celery async]

Celery task:
  → fetch_post(url)  — cascade:
      1. FxTwitter API (api.fxtwitter.com)   ← primary, no auth
      2. Nitter instances (health-checked)    ← fallback
      raises ValueError if all sources fail
  → extract GitHub repo links from post text
  → fetch GitHub READMEs (api.github.com + raw.githubusercontent.com)
  → format_as_markdown()
  → chunk → embed → store in RAG DB (source_type='xpost')
  → return { synced: 1, chunks: N }
```

### DB migration: source_type CHECK constraint

The `documents` table has a CHECK constraint on `source_type`. Add `'xpost'`:
```sql
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_source_type_check;
ALTER TABLE documents ADD CONSTRAINT documents_source_type_check
  CHECK (source_type IN ('upload', 'crawl', 'youtube', 'xpost'));
```

Add to `db-init/01-init-rag.sql` for fresh installs and run manually on existing DB.

### Markdown output format

```markdown
# Post by @{author}
Source: {url}
Date: {date}

{post text}

---

## GitHub: {owner}/{repo}
**{description}**
URL: https://github.com/{owner}/{repo}

{README content, truncated at 15 000 chars}
```

### What already exists

- `ingestion/xpost.py` — `fetch_post()`, `process_xpost()`, `fetch_github_readme()` — written, untested
- `api/routes/documents.py` — URL validation regex present (line 515), endpoint stub may exist

### What needs to be added

- Celery task: `tasks/xpost_ingest_task.py` — `ingest_xpost_task(url, user_id)`
- Endpoint: `POST /api/v1/documents/ingest-xpost` registered in `documents.py`
- DB migration: add `'xpost'` to `source_type` CHECK constraint
- Smoke test: curl with a real X post URL

### Nitter fallback strategy

Nitter instances are notoriously unstable. Current code has 2 hardcoded hosts (`nitter.privacydev.net`, `nitter.poast.org`). Improvements:

- Expand to 4-5 instances: add `nitter.lucabased.xyz`, `nitter.woodland.cafe`, `xcancel.com`
- **Quick health check** before using: HEAD request with 3s timeout — skip instance if unresponsive
- If all Nitter instances fail and FxTwitter also failed, store error in document status with clear message ("Could not fetch post from any source")
- Do NOT retry endlessly — fail fast so user can retry manually

### Fallback resilience

FxTwitter is the primary source (no Cloudflare, returns JSON, no auth). If it returns non-200, try health-checked Nitter instances in sequence. If all fail, task fails with clear error message stored in document status.

---

## 4. llm-proxy MCP

### File: `mcp-servers/llm-proxy/server.py`

**Changes:**
1. Convert all helpers to `async def` using `httpx.AsyncClient`
2. Add `ask_ollama` tool
3. Standardize: `timeout=60`, 3 attempts (initial + 2 retries, 1s sleep between) on all three tools
4. MCP tools become `async def` (FastMCP supports native async)

### `ask_ollama` spec

```python
@mcp.tool()
async def ask_ollama(
    prompt: str,
    model: str = "gemma3:4b",
    system_prompt: Optional[str] = None,
    max_tokens: int = 4096,
) -> str:
    """Ask local Ollama (localhost:11434).
    Available models: gemma3:4b, qwen3:4b, qwen3:1.7b, qwen2.5-coder:3b, ministral-3:3b"""
```

- Endpoint: `POST http://localhost:11434/api/chat`
- Payload: `{"model": model, "messages": [...], "stream": false, "options": {"num_predict": max_tokens}}`
- Retry logic: 3 attempts, `httpx.TimeoutException` + `httpx.ConnectError` caught, 1s sleep between

### Unified helper pattern (all three tools)

```python
async def _call_with_retry(coro_factory, max_attempts=3):
    """Generic retry wrapper for async HTTP calls."""
    for attempt in range(max_attempts):
        try:
            return await coro_factory()
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            if attempt == max_attempts - 1:
                return f"ERROR: unreachable after {max_attempts} attempts: {e}"
            await asyncio.sleep(1)
        except Exception as e:
            return f"ERROR: {e}"


async def _call_ollama(prompt, model, system_prompt, max_tokens):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    async def _do():
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "http://localhost:11434/api/chat",
                json={"model": model, "messages": messages, "stream": False,
                      "options": {"num_predict": max_tokens}},
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]

    return await _call_with_retry(_do)
```

Same pattern for `_call_gemini` and `_call_openrouter` (replace `requests` with `httpx.AsyncClient`).

### MCP startup fix

Check and install missing packages in Python 3.11:
```
pip install google-generativeai mcp[cli] httpx
```

The `requests` import will be removed (replaced by `httpx`).

### Settings.json (already configured)

```json
"llm-proxy": {
  "command": "C:\\Users\\DAMA\\AppData\\Local\\Programs\\Python\\Python311\\python.exe",
  "args": ["-W", "ignore", "C:\\Users\\DAMA\\Documents\\docker\\n8n\\mcp-servers\\llm-proxy\\server.py"],
  "env": { "GEMINI_API_KEY": "...", "OPENROUTER_API_KEY": "..." }
}
```

No changes needed to settings.json — only `server.py` changes.

---

## 5. Files Changed

| File | Change |
|------|--------|
| `RAG/backend/ingestion/transcriber.py` | Groq retry-after (default 300s), ffmpeg silencedetect chunking, overlap dedup, large-v3-turbo, WHISPER_THREADS |
| `RAG/backend/api/routes/documents.py` | Wire `POST /ingest-xpost` endpoint + `POST /{id}/reprocess` endpoint |
| `RAG/backend/tasks/xpost_ingest_task.py` | New Celery task for X post ingestion |
| `RAG/docker-compose-app.yml` | `WHISPER_MODEL_SIZE=large-v3-turbo`, `WHISPER_THREADS=6` |
| `RAG/db-init/01-init-rag.sql` | Add `'xpost'` to `source_type` CHECK constraint |
| `mcp-servers/llm-proxy/server.py` | Add `ask_ollama`, convert to httpx async, retry logic |

---

## 6. Out of Scope

- YouTube transcript ingestion via youtube-transcript-api (separate future task)
- HF Space transcription endpoint (not needed with large-v3-turbo local)
- GPU acceleration for Whisper (no GPU in current Docker setup)
