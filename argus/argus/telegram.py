import os
import httpx

_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")


def send_message(text: str) -> None:
    if not _TOKEN or not _CHAT:
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{_TOKEN}/sendMessage",
            json={"chat_id": _CHAT, "text": text},
            timeout=10,
        )
    except Exception:
        pass
