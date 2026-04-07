"""
RAG System — Audio/Video Transcriber
Cascade: Groq Whisper API (fast) → local faster-whisper (fallback).
Supports: MP3, WAV, M4A, OGG, FLAC, MP4, MKV, AVI, MOV, WEBM
"""

import logging
import subprocess
import tempfile
import os
import math
import re
import time
from pathlib import Path

import httpx

logger = logging.getLogger("rag.ingestion.transcriber")

# --- Groq Whisper API ---

GROQ_API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MAX_FILE_SIZE = 24 * 1024 * 1024  # 24 MB (safe margin under 25 MB limit)
GROQ_SEGMENT_DURATION = 1200  # 20 minutes per segment


def _get_groq_key() -> str | None:
    key = os.environ.get("GROQ_API_KEY", "")
    return key if key else None


def _convert_to_mp3(input_path: str, output_path: str, start: float = 0, duration: float | None = None) -> None:
    """Convert audio to MP3 64kbps (small file for API upload)."""
    cmd = ["ffmpeg", "-y", "-i", input_path]
    if start > 0:
        cmd = ["ffmpeg", "-y", "-ss", str(start), "-i", input_path]
    if duration:
        cmd.extend(["-t", str(duration)])
    cmd.extend(["-vn", "-acodec", "libmp3lame", "-ab", "64k", "-ar", "16000", "-ac", "1", output_path])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg MP3 conversion failed: {result.stderr[:500]}")


def _get_audio_duration(path: str) -> float:
    """Get audio duration in seconds using ffprobe."""
    cmd = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr[:300]}")
    return float(result.stdout.strip())


def _groq_transcribe_file(mp3_path: str, language: str | None = None) -> list[dict]:
    """Send a single MP3 file to Groq Whisper API. Returns segments.
    Retries up to 3 times on HTTP 429 using Retry-After header."""
    api_key = _get_groq_key()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    file_size = os.path.getsize(mp3_path)
    if file_size > 25 * 1024 * 1024:
        raise ValueError(f"File too large for Groq API: {file_size / 1024 / 1024:.1f} MB")

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
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
            retry_after = int(response.headers.get("Retry-After", 300))
            if attempt < max_attempts:
                logger.warning(
                    "Groq API rate limited (429), attempt %d/%d — sleeping %ds before retry",
                    attempt, max_attempts, retry_after,
                )
                time.sleep(retry_after)
                continue
            else:
                raise RuntimeError(
                    f"Groq API rate limited (429) after {max_attempts} attempts. "
                    f"Last Retry-After: {retry_after}s"
                )

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

    # Should never reach here
    raise RuntimeError(f"Groq API failed after {max_attempts} attempts")


def _groq_transcribe(audio_path: str, language: str | None = None) -> list[dict]:
    """Transcribe via Groq API, splitting into chunks if file > 24 MB."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Convert full file to MP3 first to check size
        full_mp3 = os.path.join(tmpdir, "full.mp3")
        _convert_to_mp3(audio_path, full_mp3)
        file_size = os.path.getsize(full_mp3)

        if file_size <= GROQ_MAX_FILE_SIZE:
            logger.info("Groq: single file upload (%.1f MB)", file_size / 1024 / 1024)
            return _groq_transcribe_file(full_mp3, language)

        # Split into segments
        duration = _get_audio_duration(audio_path)
        num_segments = math.ceil(file_size / GROQ_MAX_FILE_SIZE)
        segment_duration = duration / num_segments
        logger.info("Groq: splitting %.0fs audio into %d segments (%.0fs each)", duration, num_segments, segment_duration)

        all_segments = []
        for i in range(num_segments):
            start = i * segment_duration
            chunk_mp3 = os.path.join(tmpdir, f"chunk_{i}.mp3")
            _convert_to_mp3(audio_path, chunk_mp3, start=start, duration=segment_duration)

            chunk_size = os.path.getsize(chunk_mp3)
            logger.info("Groq: chunk %d/%d (%.1f MB, start=%.0fs)", i + 1, num_segments, chunk_size / 1024 / 1024, start)

            chunk_segments = _groq_transcribe_file(chunk_mp3, language)
            # Offset timestamps by chunk start time
            for seg in chunk_segments:
                seg["start"] += start
            all_segments.extend(chunk_segments)

        return all_segments


# --- Local faster-whisper fallback ---

_model = None
_model_size = os.environ.get("WHISPER_MODEL_SIZE", "small")


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        logger.info("Loading local Whisper model '%s' (first load may take 30-60s)...", _model_size)
        _model = WhisperModel(
            _model_size,
            device="cpu",
            compute_type="int8",
            cpu_threads=int(os.environ.get("WHISPER_THREADS", "4")),
        )
        logger.info("Local Whisper model loaded.")
    return _model


def _detect_silences(audio_path: str) -> list[float]:
    """Detect silence midpoints in audio using ffmpeg silencedetect filter.
    Returns list of midpoint timestamps (floats) in seconds."""
    cmd = [
        "ffmpeg", "-i", audio_path,
        "-af", "silencedetect=noise=-35dB:d=0.5",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    stderr = result.stderr

    starts = [float(m) for m in re.findall(r"silence_start:\s*([\d.]+)", stderr)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*([\d.]+)", stderr)]

    midpoints = []
    for s, e in zip(starts, ends):
        midpoints.append((s + e) / 2.0)

    logger.debug("_detect_silences: found %d silence gaps → %d midpoints", len(starts), len(midpoints))
    return midpoints


def _split_at_silences(
    audio_path: str,
    target_chunk_seconds: float = 300,
    max_chunk_seconds: float = 600,
    overlap_seconds: float = 10,
) -> list[tuple[float, float]]:
    """Split audio at silence midpoints into (start, end) tuples.

    Strategy:
    - If duration <= max_chunk_seconds: return single chunk.
    - Otherwise detect silences and walk through audio, finding the silence
      closest to target_chunk_seconds but within max_chunk_seconds.
    - If no silence found in window, hard-split at max_chunk_seconds.
    - Each chunk end is extended by overlap_seconds (capped at total duration).
    - Tiny tail chunks (< 30s) are merged into the previous chunk.
    """
    duration = _get_audio_duration(audio_path)

    if duration <= max_chunk_seconds:
        logger.info("_split_at_silences: file %.0fs <= max %.0fs, single chunk", duration, max_chunk_seconds)
        return [(0.0, duration)]

    silences = _detect_silences(audio_path)
    logger.info(
        "_split_at_silences: %.0fs audio → target=%.0fs, max=%.0fs, overlap=%.0fs, %d silence points",
        duration, target_chunk_seconds, max_chunk_seconds, overlap_seconds, len(silences),
    )

    chunks: list[tuple[float, float]] = []
    chunk_start = 0.0
    min_split_into_chunk = 60.0  # must be at least 60s into a chunk before splitting

    while chunk_start < duration:
        remaining = duration - chunk_start
        if remaining <= max_chunk_seconds:
            # Last chunk — check if it's a tiny tail that should merge
            if chunks and remaining < 30.0:
                # Extend previous chunk to cover the tail
                prev_start, prev_end = chunks[-1]
                chunks[-1] = (prev_start, min(duration + overlap_seconds, duration))
                logger.debug("_split_at_silences: tiny tail %.1fs merged into previous chunk", remaining)
            else:
                chunks.append((chunk_start, duration))
            break

        # Find best silence midpoint to split at
        target_end = chunk_start + target_chunk_seconds
        hard_end = chunk_start + max_chunk_seconds
        earliest_split = chunk_start + min_split_into_chunk

        # Gather silence midpoints within (earliest_split, hard_end)
        candidates = [s for s in silences if earliest_split < s <= hard_end]

        if candidates:
            # Pick the silence closest to target_end
            best = min(candidates, key=lambda s: abs(s - target_end))
            split_at = best
        else:
            # Hard split
            split_at = hard_end

        chunk_end = min(split_at + overlap_seconds, duration)
        chunks.append((chunk_start, chunk_end))
        logger.debug(
            "_split_at_silences: chunk %d [%.1f – %.1f] (split at %.1f + %.1f overlap)",
            len(chunks), chunk_start, chunk_end, split_at, overlap_seconds,
        )
        chunk_start = split_at  # next chunk starts at the split point (before overlap)

    logger.info("_split_at_silences: %d chunks for %.0fs audio", len(chunks), duration)
    return chunks


def _transcribe_single(model, audio_path: str, language: str | None = None) -> list[dict]:
    """Transcribe a single audio file with faster-whisper. Returns segments."""
    segments_iter, info = model.transcribe(
        audio_path,
        beam_size=int(os.environ.get("WHISPER_BEAM_SIZE", "5")),
        language=language,
        vad_filter=True,
        word_timestamps=False,
    )
    logger.info("Detected language: %s (%.0f%%)", info.language, info.language_probability * 100)

    result = []
    for seg in segments_iter:
        text = seg.text.strip()
        if text:
            result.append({
                "text": text,
                "start": seg.start,
                "duration": seg.end - seg.start,
            })
    return result


def _local_transcribe(audio_path: str, language: str | None = None) -> list[dict]:
    """Transcribe using local faster-whisper (CPU).
    Short files (≤ 600s) are transcribed directly.
    Long files are split at silence boundaries, transcribed in chunks,
    and overlap segments are deduplicated."""
    model = _get_model()
    logger.info("Local Whisper: transcribing %s (language=%s)", audio_path, language or "auto")

    duration = _get_audio_duration(audio_path)

    if duration <= 600:
        result = _transcribe_single(model, audio_path, language)
        logger.info("Local Whisper done: %d segments", len(result))
        return result

    # Long file — VAD-chunked transcription
    chunks = _split_at_silences(audio_path)

    all_segments: list[dict] = []
    last_end_time: float = 0.0

    with tempfile.TemporaryDirectory() as tmpdir:
        for idx, (chunk_start, chunk_end) in enumerate(chunks):
            chunk_duration = chunk_end - chunk_start
            chunk_wav = os.path.join(tmpdir, f"chunk_{idx}.wav")

            logger.info(
                "Local Whisper: chunk %d/%d [%.1f – %.1f] (%.1fs)",
                idx + 1, len(chunks), chunk_start, chunk_end, chunk_duration,
            )

            # Extract chunk as 16kHz mono WAV
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(chunk_start),
                "-i", audio_path,
                "-t", str(chunk_duration),
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                chunk_wav,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg chunk extraction failed: {result.stderr[:500]}")

            chunk_segments = _transcribe_single(model, chunk_wav, language)

            # Offset timestamps and deduplicate overlap
            for seg in chunk_segments:
                absolute_start = seg["start"] + chunk_start
                # Skip segments that fall within the overlap of previous chunk
                if absolute_start < last_end_time - 0.5:
                    continue
                all_segments.append({
                    "text": seg["text"],
                    "start": absolute_start,
                    "duration": seg["duration"],
                })
                last_end_time = absolute_start + seg["duration"]

    logger.info("Local Whisper done: %d segments (chunked from %.0fs audio)", len(all_segments), duration)
    return all_segments


# --- Public API ---

def is_video(path: str) -> bool:
    video_exts = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv"}
    return Path(path).suffix.lower() in video_exts


def extract_audio(video_path: str, output_path: str) -> None:
    """Extract audio from video using ffmpeg."""
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[:500]}")


def transcribe(file_path: str, language: str | None = None) -> list[dict]:
    """
    Transcribe audio/video file.
    Cascade: Groq API → local faster-whisper.
    Returns list of {"text": str, "start": float, "duration": float}.
    """
    audio_path = file_path

    with tempfile.TemporaryDirectory() as tmpdir:
        if is_video(file_path):
            audio_path = os.path.join(tmpdir, "audio.wav")
            logger.info("Extracting audio from video: %s", file_path)
            extract_audio(file_path, audio_path)

        # Try Groq API first
        if _get_groq_key():
            try:
                logger.info("Trying Groq Whisper API...")
                segments = _groq_transcribe(audio_path, language)
                logger.info("Groq transcription done: %d segments", len(segments))
                return segments
            except Exception as e:
                logger.warning("Groq API failed (%s), falling back to local Whisper", e)

        # Fallback to local whisper
        return _local_transcribe(audio_path, language)


def segments_to_markdown(segments: list[dict], title: str) -> str:
    """Convert transcript segments to timestamped markdown."""
    lines = [f"# {title}\n"]
    for seg in segments:
        start = seg["start"]
        minutes = int(start // 60)
        seconds = int(start % 60)
        lines.append(f"[{minutes:02d}:{seconds:02d}] {seg['text']}")
    return "\n".join(lines)
