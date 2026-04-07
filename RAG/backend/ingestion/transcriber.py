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
        _model = WhisperModel(_model_size, device="cpu", compute_type="int8")
        logger.info("Local Whisper model loaded.")
    return _model


def _local_transcribe(audio_path: str, language: str | None = None) -> list[dict]:
    """Transcribe using local faster-whisper (CPU)."""
    model = _get_model()

    logger.info("Local Whisper: transcribing %s (language=%s)", audio_path, language or "auto")
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

    logger.info("Local Whisper done: %d segments", len(result))
    return result


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
