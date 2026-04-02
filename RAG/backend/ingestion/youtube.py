"""
RAG System — YouTube Transcript Fetcher
Uses yt-dlp to download subtitles (handles YouTube IP/auth restrictions).
"""

import logging
import re
import tempfile
import os
import time

import httpx
import yt_dlp

logger = logging.getLogger("rag.ingestion.youtube")


def extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats."""
    patterns = [
        r"(?:v=|youtu\.be/|embed/|shorts/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


async def fetch_video_metadata(video_id: str) -> dict:
    """Fetch video title and author via YouTube oEmbed (no API key needed)."""
    oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(oembed_url)
            resp.raise_for_status()
            data = resp.json()
            return {"title": data.get("title", video_id), "author": data.get("author_name", "")}
    except Exception as exc:
        logger.warning("Could not fetch oEmbed metadata for %s: %s", video_id, exc)
        return {"title": video_id, "author": ""}


def fetch_transcript(video_id: str, languages: list[str] | None = None) -> list[dict]:
    """
    Download transcript via yt-dlp. Returns list of {"text", "start", "duration"}.
    Raises ValueError if no subtitles available.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    langs = languages or ["pl", "en"]
    lang_str = ",".join(langs)

    with tempfile.TemporaryDirectory() as tmpdir:
        ydl_opts = {
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": langs,
            "subtitlesformat": "vtt",
            "skip_download": True,
            "outtmpl": os.path.join(tmpdir, "%(id)s"),
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "sleep_interval": 2,
            "max_sleep_interval": 5,
        }

        last_exc = None
        for attempt in range(3):
            if attempt > 0:
                wait = 10 * attempt
                logger.info("Retry %d/%d after %ds (rate limit)", attempt + 1, 3, wait)
                time.sleep(wait)
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                if "429" not in str(exc) and "Too Many Requests" not in str(exc):
                    break  # non-429 error, don't retry

        if last_exc:
            raise ValueError(f"yt-dlp download failed after retries: {last_exc}") from last_exc

        # Find downloaded VTT file (try preferred lang order)
        vtt_file = None
        for lang in langs + ["en", "pl"]:
            candidate = os.path.join(tmpdir, f"{video_id}.{lang}.vtt")
            if os.path.exists(candidate):
                vtt_file = candidate
                break

        # Fallback: any .vtt file
        if not vtt_file:
            for f in os.listdir(tmpdir):
                if f.endswith(".vtt"):
                    vtt_file = os.path.join(tmpdir, f)
                    break

        if not vtt_file:
            raise ValueError(f"No subtitles found for video {video_id}. The video may have subtitles disabled.")

        return _parse_vtt(open(vtt_file, encoding="utf-8").read())


def _parse_vtt(content: str) -> list[dict]:
    """Parse WebVTT subtitle file into transcript segments."""
    segments = []
    lines = content.splitlines()
    i = 0
    seen_texts = set()  # deduplicate repeated lines

    while i < len(lines):
        line = lines[i].strip()
        # Time line: 00:00:01.000 --> 00:00:03.000
        if "-->" in line:
            time_match = re.match(
                r"(\d+):(\d+):(\d+\.\d+)\s*-->\s*(\d+):(\d+):(\d+\.\d+)", line
            )
            if time_match:
                h, m, s = time_match.group(1, 2, 3)
                start = int(h) * 3600 + int(m) * 60 + float(s)
                eh, em, es = time_match.group(4, 5, 6)
                end = int(eh) * 3600 + int(em) * 60 + float(es)
                duration = end - start

                i += 1
                text_lines = []
                while i < len(lines) and lines[i].strip():
                    text_lines.append(lines[i].strip())
                    i += 1

                text = " ".join(text_lines)
                # Strip VTT tags like <c>, <00:00:01.000>
                text = re.sub(r"<[^>]+>", "", text).strip()

                if text and text not in seen_texts:
                    seen_texts.add(text)
                    segments.append({"text": text, "start": start, "duration": duration})
        i += 1

    return segments


def download_audio(video_id: str, output_dir: str) -> str:
    """Download audio from YouTube video via yt-dlp. Returns path to WAV file."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    output_path = os.path.join(output_dir, f"{video_id}.wav")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(output_dir, f"{video_id}.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "wav",
        }],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }

    last_exc = None
    for attempt in range(3):
        if attempt > 0:
            wait = 10 * attempt
            logger.info("Audio download retry %d/%d after %ds", attempt + 1, 3, wait)
            time.sleep(wait)
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            if "429" not in str(exc) and "Too Many Requests" not in str(exc):
                break

    if last_exc:
        raise ValueError(f"yt-dlp audio download failed: {last_exc}") from last_exc

    if not os.path.exists(output_path):
        raise FileNotFoundError(f"Expected audio file not found: {output_path}")

    logger.info("Downloaded audio: %s (%.1f MB)", output_path, os.path.getsize(output_path) / 1024 / 1024)
    return output_path


def segments_to_markdown(segments: list[dict], title: str) -> str:
    """Convert transcript segments to markdown with timestamps."""
    lines = [f"# {title}\n"]
    for seg in segments:
        start = seg["start"]
        minutes = int(start // 60)
        seconds = int(start % 60)
        text = seg["text"].replace("\n", " ").strip()
        if text:
            lines.append(f"[{minutes:02d}:{seconds:02d}] {text}")
    return "\n".join(lines)
