#!/usr/bin/env python3
# pip install httpx google-generativeai numpy

import json
import os
import subprocess
import sys
import time

import httpx
import numpy as np
import google.generativeai as genai


# --- Config ---
CONTAINER_NAME = "rag-worker"
CONTAINER_PATH = "/tmp/transcription.json"
OUTPUT_FILE = "./transcription_output.json"
RESULTS_FILE = "./benchmark_results.json"
OLLAMA_URL = "http://localhost:11434/api/embed"
OLLAMA_MODEL = "qwen3-embedding:0.6b"
GEMINI_EMBED_MODEL = "models/gemini-embedding-001"
GEMINI_LLM_MODEL = "gemini-2.0-flash"
CHUNK_SIZE = 2000
CHUNK_OVERLAP = 100


def fmt_hms(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def cosine_sim(a: list, b: list) -> float:
    a, b = np.array(a, dtype=float), np.array(b, dtype=float)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def step_load_transcription() -> dict:
    t0 = time.time()
    if os.path.exists(OUTPUT_FILE):
        print(f"[LOAD] Using local file: {OUTPUT_FILE}", flush=True)
    else:
        print(f"[LOAD] Local file not found, copying from container...", flush=True)
        result = subprocess.run(
            ["docker", "cp", f"{CONTAINER_NAME}:{CONTAINER_PATH}", OUTPUT_FILE],
            capture_output=True,
            text=True,
            env={**os.environ, "MSYS_NO_PATHCONV": "1"},
        )
        if result.returncode != 0:
            print(f"[LOAD] ERROR: {result.stderr}", flush=True)
            sys.exit(1)
    elapsed = time.time() - t0
    print(f"[LOAD] Done in {elapsed:.2f}s", flush=True)

    with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def step_verify(data: dict):
    t0 = time.time()
    duration_mp3 = data.get("duration_mp3", 0.0)
    segments = data.get("segments", [])
    last_end = segments[-1]["end"] if segments else 0.0
    diff = abs(duration_mp3 - last_end)
    status = "OK" if diff <= 30 else "WARN"
    elapsed = time.time() - t0
    print(
        f"[VERIFY] MP3: {fmt_hms(duration_mp3)} | Last segment: {fmt_hms(last_end)} "
        f"| diff: {diff:.1f}s | {status}  ({elapsed:.2f}s)",
        flush=True,
    )


def step_quality_check(full_text: str):
    """Quality check via OpenRouter free models (Gemini LLM quota exhausted)."""
    t0 = time.time()
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not openrouter_key:
        print("[QUALITY] SKIP - no OPENROUTER_API_KEY set", flush=True)
        return

    length = len(full_text)
    fragments = {
        "start": full_text[:500],
        "middle": full_text[max(0, length // 2 - 250): length // 2 + 250],
        "end": full_text[max(0, length - 500):],
    }
    labels = ["start", "middle", "end"]
    client = httpx.Client(timeout=60.0)
    for idx, label in enumerate(labels, 1):
        text = fragments[label].strip()
        prompt = (
            "Ocen jakosc tej polskiej transkrypcji audio. "
            "Czy tekst jest sensowny, spojny, nie uciety? "
            f"Odpowiedz krotko: OK/PROBLEMY + 1 zdanie. Fragment: {text}"
        )
        try:
            resp = client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "google/gemma-3-27b-it:free",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 256,
                },
            )
            resp.raise_for_status()
            answer = resp.json()["choices"][0]["message"]["content"].strip().replace("\n", " ")
        except Exception as e:
            answer = f"ERROR: {e}"
        print(f"[QUALITY] Fragment {idx}/3 ({label}): {answer}", flush=True)
    client.close()
    elapsed = time.time() - t0
    print(f"[QUALITY] Done in {elapsed:.2f}s", flush=True)


def step_chunk(full_text: str) -> list:
    t0 = time.time()
    chunks = []
    start = 0
    while start < len(full_text):
        end = start + CHUNK_SIZE
        chunks.append(full_text[start:end])
        start += CHUNK_SIZE - CHUNK_OVERLAP
    total = len(chunks)
    avg_len = int(sum(len(c) for c in chunks) / total) if total else 0
    elapsed = time.time() - t0
    print(f"[CHUNK] {total} chunks created (avg {avg_len} chars) in {elapsed:.2f}s", flush=True)
    return chunks


def step_embed_ollama(chunks: list) -> list:
    t0 = time.time()
    vectors = []
    client = httpx.Client(timeout=120.0)
    for i, chunk in enumerate(chunks, 1):
        chunk_t0 = time.time()
        resp = client.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "input": chunk},
        )
        resp.raise_for_status()
        embedding = resp.json()["embeddings"][0]
        vectors.append(embedding)
        chunk_elapsed = time.time() - chunk_t0
        if i % 5 == 0 or i == len(chunks):
            total_elapsed = time.time() - t0
            avg_ms = (total_elapsed / i) * 1000
            print(
                f"[EMBED-OLLAMA] chunk {i}/{len(chunks)} | avg {avg_ms:.0f}ms/chunk | elapsed: {total_elapsed:.1f}s",
                flush=True,
            )
    client.close()
    total_elapsed = time.time() - t0
    print(f"[EMBED-OLLAMA] Done — {len(vectors)} vectors in {total_elapsed:.2f}s", flush=True)
    return vectors


def step_embed_gemini(chunks: list) -> list:
    t0 = time.time()
    vectors = []
    max_retries = 3
    for i, chunk in enumerate(chunks, 1):
        for attempt in range(max_retries):
            try:
                result = genai.embed_content(model=GEMINI_EMBED_MODEL, content=chunk)
                vectors.append(result["embedding"])
                break
            except Exception as e:
                if "429" in str(e) and attempt < max_retries - 1:
                    wait = 10 * (attempt + 1)
                    print(f"[EMBED-GEMINI] Rate limited, waiting {wait}s...", flush=True)
                    time.sleep(wait)
                else:
                    print(f"[EMBED-GEMINI] ERROR chunk {i}: {e}", flush=True)
                    return vectors  # Return what we have so far
        if i % 5 == 0 or i == len(chunks):
            total_elapsed = time.time() - t0
            avg_ms = (total_elapsed / i) * 1000
            print(
                f"[EMBED-GEMINI] chunk {i}/{len(chunks)} | avg {avg_ms:.0f}ms/chunk | elapsed: {total_elapsed:.1f}s",
                flush=True,
            )
    total_elapsed = time.time() - t0
    print(f"[EMBED-GEMINI] Done — {len(vectors)} vectors in {total_elapsed:.2f}s", flush=True)
    return vectors


def intra_model_consistency(vectors: list) -> float:
    if len(vectors) < 2:
        return 1.0
    sims = [cosine_sim(vectors[i], vectors[i + 1]) for i in range(len(vectors) - 1)]
    return float(np.mean(sims))


def step_report(chunks: list, ollama_vectors: list, gemini_vectors: list,
                ollama_time: float, gemini_time: float) -> dict:
    n = len(chunks)
    ollama_dims = len(ollama_vectors[0]) if ollama_vectors else 0
    gemini_dims = len(gemini_vectors[0]) if gemini_vectors else 0

    ollama_avg = (ollama_time / n * 1000) if n else 0
    gemini_avg = (gemini_time / n * 1000) if n else 0

    ollama_consistency = intra_model_consistency(ollama_vectors)
    gemini_consistency = intra_model_consistency(gemini_vectors)

    print("\n" + "=" * 65, flush=True)
    print(f"{'[REPORT] Embedding Benchmark Results':^65}", flush=True)
    print("=" * 65, flush=True)
    print(
        f"{'Model':<28} {'Dims':>5} {'Total(s)':>9} {'Avg(ms)':>8} {'Chunks':>7}",
        flush=True,
    )
    print("-" * 65, flush=True)
    print(
        f"{'Ollama ' + OLLAMA_MODEL:<28} {ollama_dims:>5} {ollama_time:>9.2f} {ollama_avg:>8.0f} {n:>7}",
        flush=True,
    )
    print(
        f"{'Gemini gemini-embedding-001':<28} {gemini_dims:>5} {gemini_time:>9.2f} {gemini_avg:>8.0f} {n:>7}",
        flush=True,
    )
    print("=" * 65, flush=True)
    print(f"[REPORT] Intra-model consistency (avg cosine sim between consecutive chunks):", flush=True)
    print(f"  Ollama:  {ollama_consistency:.4f}", flush=True)
    print(f"  Gemini:  {gemini_consistency:.4f}", flush=True)
    print(
        "[REPORT] Cross-model agreement: dimensions differ "
        f"({ollama_dims}d vs {gemini_dims}d) — direct cosine comparison not applicable.",
        flush=True,
    )
    print("=" * 65, flush=True)

    results = {
        "models": [
            {
                "name": OLLAMA_MODEL,
                "provider": "ollama",
                "dimensions": ollama_dims,
                "total_time_s": round(ollama_time, 3),
                "avg_time_ms_per_chunk": round(ollama_avg, 1),
                "total_chunks": n,
                "intra_consistency": round(ollama_consistency, 4),
            },
            {
                "name": "text-embedding-004",
                "provider": "gemini",
                "dimensions": gemini_dims,
                "total_time_s": round(gemini_time, 3),
                "avg_time_ms_per_chunk": round(gemini_avg, 1),
                "total_chunks": n,
                "intra_consistency": round(gemini_consistency, 4),
            },
        ],
        "note_cross_model": "Dimensions differ — direct cosine comparison not applicable.",
    }
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"[REPORT] Results saved to {RESULTS_FILE}", flush=True)
    return results


def main():
    # --- Early env check ---
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[ERROR] GEMINI_API_KEY env var is not set. Exiting.", flush=True)
        sys.exit(1)
    genai.configure(api_key=api_key)

    script_t0 = time.time()
    print(f"[START] transcribe_benchmark.py", flush=True)

    # Step 1: Load transcription
    data = step_load_transcription()

    # Step 2: Verify
    step_verify(data)

    # Build full text from segments
    segments = data.get("segments", [])
    full_text = " ".join(seg.get("text", "").strip() for seg in segments)
    if not full_text:
        full_text = data.get("text", "")
    print(f"[TEXT] Total characters: {len(full_text)}", flush=True)

    # Step 3: Quality (via OpenRouter free models)
    step_quality_check(full_text)

    # Step 4: Chunking
    chunks = step_chunk(full_text)

    # Step 5: Embed Ollama
    t0 = time.time()
    ollama_vectors = step_embed_ollama(chunks)
    ollama_time = time.time() - t0

    # Step 6: Embed Gemini
    t0 = time.time()
    gemini_vectors = step_embed_gemini(chunks)
    gemini_time = time.time() - t0

    # Step 7: Report
    step_report(chunks, ollama_vectors, gemini_vectors, ollama_time, gemini_time)

    total_elapsed = time.time() - script_t0
    print(f"\n[DONE] Total elapsed: {total_elapsed:.1f}s", flush=True)


if __name__ == "__main__":
    main()
