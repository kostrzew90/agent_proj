# Transcription Fix + X Post Ingestion + llm-proxy MCP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix OOM transcription crash (Groq retry + VAD-chunked local fallback), wire X post ingestion end-to-end, add `ask_ollama` to llm-proxy MCP.

**Architecture:** Three independent changes. (1) `transcriber.py` gets Groq 429 retry logic and chunked local fallback using ffmpeg `silencedetect` + overlap dedup. (2) X post endpoint already exists — fix `source_type`, add Nitter health-check, add DB constraint migration. (3) `llm-proxy/server.py` gets `ask_ollama` tool, all helpers converted to async httpx with retry.

**Tech Stack:** faster-whisper (large-v3-turbo), ffmpeg silencedetect, httpx (async), FastMCP, FxTwitter API

**Spec:** `docs/superpowers/specs/2026-04-07-transcription-xpost-mcp-design.md`

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `RAG/backend/ingestion/transcriber.py` | Groq retry + VAD-chunked local fallback | Modify |
| `RAG/docker-compose-app.yml` | Worker env vars (model, threads) | Modify |
| `RAG/backend/api/routes/documents.py` | Fix xpost source_type + add reprocess endpoint | Modify |
| `RAG/backend/ingestion/xpost.py` | Nitter health-check, more instances | Modify |
| `RAG/db-init/01-init-rag.sql` | Add 'youtube','xpost' to CHECK constraint | Modify |
| `mcp-servers/llm-proxy/server.py` | ask_ollama + async httpx + retry | Rewrite |

---

## Task 1: Transcriber — Groq retry on 429

**Files:**
- Modify: `RAG/backend/ingestion/transcriber.py:52-93` (function `_groq_transcribe_file`)

- [ ] **Step 1: Add retry logic to `_groq_transcribe_file`**

Replace the function `_groq_transcribe_file` (lines 52-93) with:

```python
def _groq_transcribe_file(mp3_path: str, language: str | None = None, max_retries: int = 3) -> list[dict]:
    """Send a single MP3 file to Groq Whisper API. Returns segments. Retries on 429."""
    api_key = _get_groq_key()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    file_size = os.path.getsize(mp3_path)
    if file_size > 25 * 1024 * 1024:
        raise ValueError(f"File too large for Groq API: {file_size / 1024 / 1024:.1f} MB")

    for attempt in range(max_retries):
        with open(mp3_path, "rb") as f:
            files = {"file": (os.path.basename(mp3_path), f, "audio/mpeg")}
            data = {
                "model": "whisper-large-v3",
                "response_format": "verbose_json",
                "timestamp_granularities[]": "segment",
            }
            if language:
                data["language"] = language

            response = httpx.post(
                GROQ_API_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                files=files,
                data=data,
                timeout=120.0,
            )

        if response.status_code == 429:
            retry_after = int(response.headers.get("retry-after", "300"))
            logger.warning(
                "Groq rate limit (attempt %d/%d), waiting %ds...",
                attempt + 1, max_retries, retry_after,
            )
            if attempt < max_retries - 1:
                import time
                time.sleep(retry_after)
                continue
            raise RuntimeError(f"Groq rate limit after {max_retries} retries")

        if response.status_code != 200:
            raise RuntimeError(f"Groq API error {response.status_code}: {response.text[:500]}")

        result = response.json()
        segments = []
        for seg in result.get("segments", []):
            text = seg.get("text", "").strip()
            if text:
                segments.append({
                    "text": text,
                    "start": seg.get("start", 0),
                    "duration": seg.get("end", 0) - seg.get("start", 0),
                })
        return segments

    raise RuntimeError("Groq: should not reach here")
```

- [ ] **Step 2: Verify Groq imports are fine**

No new imports needed — `httpx`, `os`, `logging` already imported. `import time` is inline.

- [ ] **Step 3: Commit**

```bash
git add RAG/backend/ingestion/transcriber.py
git commit -m "fix(transcriber): add Groq 429 retry with Retry-After header parsing"
```

---

## Task 2: Transcriber — VAD-chunked local fallback

**Files:**
- Modify: `RAG/backend/ingestion/transcriber.py:132-175` (functions `_get_model`, `_local_transcribe`)

- [ ] **Step 1: Update `_get_model` to use WHISPER_THREADS**

Replace `_get_model` (lines 138-145) with:

```python
def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        cpu_threads = int(os.environ.get("WHISPER_THREADS", "4"))
        logger.info(
            "Loading local Whisper model '%s' (threads=%d, first load may take 30-60s)...",
            _model_size, cpu_threads,
        )
        _model = WhisperModel(_model_size, device="cpu", compute_type="int8", cpu_threads=cpu_threads)
        logger.info("Local Whisper model loaded.")
    return _model
```

- [ ] **Step 2: Add `_detect_silences` function**

Add after `_get_model` function:

```python
def _detect_silences(audio_path: str, min_silence_duration: float = 0.5, noise_threshold: int = -35) -> list[float]:
    """Detect silence timestamps using ffmpeg silencedetect. Returns list of silence midpoints in seconds."""
    cmd = [
        "ffmpeg", "-i", audio_path, "-af",
        f"silencedetect=noise={noise_threshold}dB:d={min_silence_duration}",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    stderr = result.stderr

    silences = []
    import re as _re
    starts = _re.findall(r"silence_start:\s*([\d.]+)", stderr)
    ends = _re.findall(r"silence_end:\s*([\d.]+)", stderr)
    for s, e in zip(starts, ends):
        midpoint = (float(s) + float(e)) / 2
        silences.append(midpoint)

    return silences


def _split_at_silences(
    audio_path: str,
    target_chunk_seconds: float = 300,  # 5 minutes
    max_chunk_seconds: float = 600,     # 10 minutes
    overlap_seconds: float = 10,
) -> list[tuple[float, float]]:
    """Split audio into chunks at silence boundaries. Returns list of (start, end) tuples."""
    duration = _get_audio_duration(audio_path)

    if duration <= max_chunk_seconds:
        return [(0, duration)]

    silences = _detect_silences(audio_path)

    chunks = []
    chunk_start = 0.0

    while chunk_start < duration - 30:  # don't create tiny tail chunks
        ideal_end = chunk_start + target_chunk_seconds
        max_end = min(chunk_start + max_chunk_seconds, duration)

        # Find best silence point near ideal_end
        best_split = None
        best_distance = float("inf")
        for s in silences:
            if chunk_start + 60 < s < max_end:  # at least 60s into chunk
                distance = abs(s - ideal_end)
                if distance < best_distance:
                    best_distance = distance
                    best_split = s

        if best_split is None:
            # No silence found — hard split at max_end
            split_point = max_end
        else:
            split_point = best_split

        # Add overlap: extend end by overlap_seconds
        chunk_end = min(split_point + overlap_seconds, duration)
        chunks.append((chunk_start, chunk_end))

        # Next chunk starts at split point (no overlap on start — dedup handles it)
        chunk_start = split_point

    # Final chunk if remaining
    if chunk_start < duration - 1:
        chunks.append((chunk_start, duration))

    logger.info(
        "Split %.0fs audio into %d chunks (target=%ds, overlap=%ds, %d silence points)",
        duration, len(chunks), target_chunk_seconds, overlap_seconds, len(silences),
    )
    return chunks
```

- [ ] **Step 3: Replace `_local_transcribe` with chunked version**

Replace `_local_transcribe` (lines 148-174) with:

```python
def _local_transcribe(audio_path: str, language: str | None = None) -> list[dict]:
    """Transcribe using local faster-whisper (CPU) with VAD-based chunking."""
    model = _get_model()
    duration = _get_audio_duration(audio_path)

    # Short files: transcribe directly
    if duration <= 600:  # 10 minutes
        return _transcribe_single(model, audio_path, language)

    # Long files: split at silence boundaries, process sequentially
    logger.info("Local Whisper: chunking %.0fs audio for safe processing", duration)
    chunk_ranges = _split_at_silences(audio_path)

    all_segments = []
    last_end_time = 0.0

    for i, (start, end) in enumerate(chunk_ranges):
        logger.info(
            "Local Whisper: chunk %d/%d (%.0f-%.0fs)",
            i + 1, len(chunk_ranges), start, end,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            chunk_path = os.path.join(tmpdir, f"chunk_{i}.wav")
            # Extract chunk via ffmpeg
            cmd = [
                "ffmpeg", "-y", "-ss", str(start), "-i", audio_path,
                "-t", str(end - start),
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                chunk_path,
            ]
            subprocess.run(cmd, capture_output=True, text=True, check=True)

            chunk_segments = _transcribe_single(model, chunk_path, language)

        # Offset timestamps and dedup overlap
        for seg in chunk_segments:
            absolute_start = seg["start"] + start
            # Dedup: skip segments that overlap with previous chunk's last segment
            if absolute_start < last_end_time - 0.5:
                continue
            seg["start"] = absolute_start
            all_segments.append(seg)
            last_end_time = absolute_start + seg["duration"]

    logger.info("Local Whisper done: %d total segments from %d chunks", len(all_segments), len(chunk_ranges))
    return all_segments


def _transcribe_single(model, audio_path: str, language: str | None = None) -> list[dict]:
    """Transcribe a single audio file (no chunking)."""
    segments, info = model.transcribe(
        audio_path,
        beam_size=int(os.environ.get("WHISPER_BEAM_SIZE", "5")),
        language=language,
        vad_filter=True,
        word_timestamps=False,
    )

    logger.info("Detected language: %s (%.0f%%)", info.language, info.language_probability * 100)

    result = []
    for seg in segments:
        text = seg.text.strip()
        if text:
            result.append({
                "text": text,
                "start": seg.start,
                "duration": seg.end - seg.start,
            })
    return result
```

- [ ] **Step 4: Commit**

```bash
git add RAG/backend/ingestion/transcriber.py
git commit -m "feat(transcriber): VAD-chunked local fallback with silencedetect + overlap dedup"
```

---

## Task 3: Docker Compose — env vars + reprocess endpoint

**Files:**
- Modify: `RAG/docker-compose-app.yml:50-52`
- Modify: `RAG/backend/api/routes/documents.py` (add reprocess endpoint after line 370)

- [ ] **Step 1: Update docker-compose-app.yml env vars**

Replace lines 50-52 in `docker-compose-app.yml`:

```yaml
      WHISPER_MODEL_SIZE: tiny
      WHISPER_BEAM_SIZE: "1"
```

With:

```yaml
      WHISPER_MODEL_SIZE: large-v3-turbo
      WHISPER_BEAM_SIZE: "5"
      WHISPER_THREADS: "6"
```

- [ ] **Step 2: Add reprocess endpoint to documents.py**

Add after the `delete_document` endpoint (after line 370), before the `CrawlRequest` class:

```python
@router.post("/{document_id}/reprocess", response_model=DocumentResponse, status_code=202)
async def reprocess_document(
    document_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reset a stuck/failed document and re-trigger processing."""
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == user.id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.status not in ("error", "processing"):
        raise HTTPException(status_code=400, detail=f"Cannot reprocess document with status '{doc.status}'")

    # Delete existing chunks
    from sqlalchemy import delete
    await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))

    # Reset document status
    doc.status = "pending"
    doc.error_message = None
    doc.processed_at = None

    # Create new processing task
    task = ProcessingTask(document_id=doc.id, task_type="full_pipeline", status="pending")
    db.add(task)
    await db.commit()
    await db.refresh(doc)

    # Dispatch Celery task
    from tasks.document_tasks import process_document
    celery_result = process_document.delay(doc.id, task.id)
    task.celery_task_id = celery_result.id
    await db.commit()

    return DocumentResponse(
        id=doc.id, filename=doc.filename, file_type=doc.file_type,
        file_size=doc.file_size, page_count=doc.page_count, status=doc.status,
        source_type=doc.source_type, source_url=doc.source_url,
        created_at=doc.created_at, processed_at=doc.processed_at,
    )
```

- [ ] **Step 3: Commit**

```bash
git add RAG/docker-compose-app.yml RAG/backend/api/routes/documents.py
git commit -m "feat: large-v3-turbo env vars + document reprocess endpoint"
```

---

## Task 4: X Post — fix source_type + DB constraint + Nitter health-check

**Files:**
- Modify: `RAG/backend/api/routes/documents.py:531`
- Modify: `RAG/backend/ingestion/xpost.py:91-106`
- Modify: `RAG/db-init/01-init-rag.sql:47-48`

- [ ] **Step 1: Fix source_type in documents.py**

In `RAG/backend/api/routes/documents.py`, line 531, change:

```python
        source_type="web_crawl",
```

To:

```python
        source_type="xpost",
```

- [ ] **Step 2: Update DB CHECK constraint in init SQL**

In `RAG/db-init/01-init-rag.sql`, line 47-48, change:

```sql
    source_type VARCHAR(20) DEFAULT 'upload'
        CHECK (source_type IN ('upload', 'api', 'watch_folder', 'web_crawl')),
```

To:

```sql
    source_type VARCHAR(20) DEFAULT 'upload'
        CHECK (source_type IN ('upload', 'api', 'watch_folder', 'web_crawl', 'youtube', 'xpost')),
```

- [ ] **Step 3: Add Nitter health-check to xpost.py**

Replace Nitter fallback block (lines 91-106) in `RAG/backend/ingestion/xpost.py` with:

```python
            logger.warning("FxTwitter failed (%s), trying Nitter", e)
            nitter_hosts = [
                "nitter.privacydev.net",
                "nitter.poast.org",
                "nitter.lucabased.xyz",
                "xcancel.com",
                "nitter.woodland.cafe",
            ]
            for nitter_host in nitter_hosts:
                try:
                    # Health check: HEAD request with short timeout
                    try:
                        health = await client.head(f"https://{nitter_host}", timeout=3.0)
                        if health.status_code >= 500:
                            logger.debug("Nitter %s unhealthy (HTTP %d), skipping", nitter_host, health.status_code)
                            continue
                    except Exception:
                        logger.debug("Nitter %s unreachable, skipping", nitter_host)
                        continue

                    nitter_url = f"https://{nitter_host}/{username}/status/{tweet_id}"
                    resp = await client.get(nitter_url, follow_redirects=True, timeout=10.0)
                    if resp.status_code == 200:
                        # Basic extraction from HTML
                        text = resp.text
                        # Find tweet content div
                        match = re.search(r'class="tweet-content[^"]*"[^>]*>(.*?)</div>', text, re.DOTALL)
                        if match:
                            content = re.sub(r"<[^>]+>", " ", match.group(1)).strip()
                            post.text = content
                            post.author = username
                            logger.info("Fetched via Nitter (%s): %d chars", nitter_host, len(post.text))
                            break
                except Exception:
                    continue
```

- [ ] **Step 4: Run DB migration on existing database**

```bash
docker exec rag-postgres psql -U rag -d rag -c "
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_source_type_check;
ALTER TABLE documents ADD CONSTRAINT documents_source_type_check
  CHECK (source_type IN ('upload', 'api', 'watch_folder', 'web_crawl', 'youtube', 'xpost'));
"
```

Expected: `ALTER TABLE` × 2

- [ ] **Step 5: Commit**

```bash
git add RAG/backend/api/routes/documents.py RAG/backend/ingestion/xpost.py RAG/db-init/01-init-rag.sql
git commit -m "fix(xpost): source_type='xpost', DB constraint migration, Nitter health-check"
```

---

## Task 5: Smoke test — rebuild and verify transcription + X post

**Files:** None (testing only)

- [ ] **Step 1: Rebuild containers**

```bash
cd RAG
docker compose -f docker-compose-infra.yml -f docker-compose-app.yml up -d --build rag-api rag-worker
```

Expected: both containers start, `rag-api` healthy.

- [ ] **Step 2: Verify health**

```bash
curl -s http://localhost:8000/api/v1/health | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin), indent=2))"
```

Expected: `{"status": "healthy", ...}`

- [ ] **Step 3: Get auth token**

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo $TOKEN
```

- [ ] **Step 4: Reprocess stuck MP3**

Find the stuck document ID first:

```bash
curl -s http://localhost:8000/api/v1/documents?status=processing \
  -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys, json
docs = json.load(sys.stdin)['documents']
for d in docs:
    print(f'ID={d[\"id\"]} file={d[\"filename\"]} status={d[\"status\"]}')
"
```

Then reprocess:

```bash
curl -s -X POST http://localhost:8000/api/v1/documents/{ID}/reprocess \
  -H "Authorization: Bearer $TOKEN"
```

Expected: `{"id": ..., "status": "pending", ...}`

Monitor worker logs:

```bash
docker logs rag-worker --tail 30 -f
```

Expected: see `Loading local Whisper model 'large-v3-turbo'`, chunk splitting, transcription progress.

- [ ] **Step 5: Smoke test X post ingestion**

```bash
curl -s -X POST http://localhost:8000/api/v1/documents/xpost \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://x.com/AnthropicAI/status/1929273948083851537"}' | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin), indent=2))"
```

Expected: `{"document_id": ..., "task_id": ..., "status": "pending"}`

Check task progress:

```bash
curl -s http://localhost:8000/api/v1/documents/tasks/{TASK_ID} \
  -H "Authorization: Bearer $TOKEN"
```

Expected: status progresses from `pending` → `running` → `completed`.

- [ ] **Step 6: Commit (if any hotfixes)**

```bash
git add -A && git commit -m "fix: smoke test hotfixes for transcription + xpost"
```

---

## Task 6: llm-proxy MCP — rewrite to async httpx + ask_ollama

**Files:**
- Rewrite: `mcp-servers/llm-proxy/server.py`

- [ ] **Step 1: Install missing packages in Python 3.11**

```bash
"C:\Users\DAMA\AppData\Local\Programs\Python\Python311\python.exe" -m pip install httpx "mcp[cli]" google-generativeai
```

Expected: packages installed successfully.

- [ ] **Step 2: Rewrite server.py**

Replace entire `mcp-servers/llm-proxy/server.py` with:

```python
import asyncio
import os
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("llm-proxy")


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

async def _call_with_retry(coro_factory, max_attempts: int = 3) -> str:
    """Generic retry wrapper for async HTTP calls."""
    for attempt in range(max_attempts):
        try:
            return await coro_factory()
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            if attempt == max_attempts - 1:
                return f"ERROR: unreachable after {max_attempts} attempts: {e}"
            await asyncio.sleep(1)
        except httpx.HTTPStatusError as e:
            return f"ERROR: HTTP {e.response.status_code}: {e.response.text[:300]}"
        except Exception as e:
            return f"ERROR: {e}"
    return "ERROR: should not reach here"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _call_gemini(
    prompt: str,
    model: str,
    system_prompt: Optional[str],
    max_tokens: int,
) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "ERROR: GEMINI_API_KEY not set"

    import google.generativeai as genai
    genai.configure(api_key=api_key)

    def _sync_call():
        generation_config = genai.GenerationConfig(max_output_tokens=max_tokens)
        if system_prompt:
            m = genai.GenerativeModel(model, system_instruction=system_prompt)
        else:
            m = genai.GenerativeModel(model)
        response = m.generate_content(
            prompt,
            generation_config=generation_config,
            request_options={"timeout": 60},
        )
        return response.text

    try:
        # google-generativeai is sync — run in thread to not block
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_call)
    except Exception as e:
        return f"ERROR: {e}"


async def _call_openrouter(
    prompt: str,
    model: str,
    system_prompt: Optional[str],
    max_tokens: int,
) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return "ERROR: OPENROUTER_API_KEY not set"

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    async def _do():
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]

    return await _call_with_retry(_do)


async def _call_ollama(
    prompt: str,
    model: str,
    system_prompt: Optional[str],
    max_tokens: int,
) -> str:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    async def _do():
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "options": {"num_predict": max_tokens},
                },
            )
            response.raise_for_status()
            return response.json()["message"]["content"]

    return await _call_with_retry(_do)


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def ask_gemini(
    prompt: str,
    model: str = "gemini-2.0-flash",
    system_prompt: Optional[str] = None,
    max_tokens: int = 4096,
) -> str:
    """Ask Gemini. Free via Google AI Studio/Google One. Good for research, analysis, text."""
    return await _call_gemini(prompt, model, system_prompt, max_tokens)


@mcp.tool()
async def ask_openrouter(
    prompt: str,
    model: str = "meta-llama/llama-4-maverick:free",
    system_prompt: Optional[str] = None,
    max_tokens: int = 4096,
) -> str:
    """Ask via OpenRouter free models to save Claude rate limits.
    Free models: meta-llama/llama-4-maverick:free, qwen/qwen3-235b-a22b:free, google/gemma-3-27b-it:free"""
    return await _call_openrouter(prompt, model, system_prompt, max_tokens)


@mcp.tool()
async def ask_ollama(
    prompt: str,
    model: str = "gemma3:4b",
    system_prompt: Optional[str] = None,
    max_tokens: int = 4096,
) -> str:
    """Ask local Ollama (localhost:11434). No internet needed.
    Available models: gemma3:4b, qwen3:4b, qwen3:1.7b, qwen2.5-coder:3b, ministral-3:3b"""
    return await _call_ollama(prompt, model, system_prompt, max_tokens)


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 3: Verify MCP starts**

```bash
"C:\Users\DAMA\AppData\Local\Programs\Python\Python311\python.exe" -c "
import subprocess, sys
proc = subprocess.Popen(
    [sys.executable, '-W', 'ignore', 'C:/Users/DAMA/Documents/docker/n8n/mcp-servers/llm-proxy/server.py'],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE
)
import time; time.sleep(3)
proc.terminate()
print('EXIT CODE:', proc.wait(timeout=5))
print('STDERR:', proc.stderr.read().decode()[:500])
"
```

Expected: exits cleanly (stdin closes → server stops). No import errors in stderr.

- [ ] **Step 4: Commit**

```bash
git add mcp-servers/llm-proxy/server.py
git commit -m "feat(mcp): add ask_ollama, convert to async httpx with retry"
```

---

## Task 7: Verify MCP tools from Claude Code

**Files:** None (testing only)

- [ ] **Step 1: Restart Claude Code session**

Close and reopen Claude Code so the llm-proxy MCP reconnects.

- [ ] **Step 2: Test ask_ollama**

In Claude Code, ask: "Use the ask_ollama tool to say hello with gemma3:4b"

Expected: Ollama responds with a greeting. If Ollama is not running, expected error: "ERROR: unreachable after 3 attempts".

- [ ] **Step 3: Test ask_gemini**

In Claude Code, ask: "Use ask_gemini to tell me what 2+2 is"

Expected: Gemini responds with "4" or similar.

- [ ] **Step 4: Test ask_openrouter**

In Claude Code, ask: "Use ask_openrouter to summarize what Claude Code is in one sentence"

Expected: OpenRouter responds with a summary.
