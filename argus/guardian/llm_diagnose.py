import os
import httpx

_GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
_GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def diagnose(anomaly_type: str, logs_snippet: str) -> str:
    """Call Gemini free tier, return 2-3 sentence diagnosis for Telegram.

    Returns "LLM diagnosis unavailable (...)" on any error.
    """
    if not _GEMINI_KEY:
        return "LLM diagnosis unavailable (no API key)"

    lines = logs_snippet.splitlines()[-50:]
    truncated = "\n".join(lines)[-10_000:]
    prompt = (
        f"Argus agent anomaly: {anomaly_type}\n\n"
        f"Recent logs:\n{truncated}\n\n"
        "What likely caused this? Answer in 2-3 sentences max."
    )
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{_GEMINI_MODEL}:generateContent?key={_GEMINI_KEY}"
    )
    try:
        r = httpx.post(
            url,
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 150, "temperature": 0},
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        return f"LLM diagnosis unavailable ({e})"
