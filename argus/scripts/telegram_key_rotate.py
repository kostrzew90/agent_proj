#!/usr/bin/env python3
"""
Host-level script (run via cron, NOT inside a container).

Polls Telegram getUpdates for messages in the configured Argus alarm chat.
When a message contains a string matching a known LLM provider API key
format (Gemini/OpenRouter/Groq), it rewrites the matching var in
~/argus/.env, restarts the `app` container, and replies with a
confirmation on Telegram. Messages from any other chat, or with no
recognizable key, are ignored.

Meant to close the loop on: alarm fires (key banned) -> you generate a
fresh key -> paste it into the Telegram chat with the bot -> this script
picks it up and rotates it into production.

Run every ~1 minute via cron:
    * * * * * cd /root/argus && /usr/bin/python3 scripts/telegram_key_rotate.py >> scripts/telegram_key_rotate.log 2>&1
"""
import fcntl
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

ARGUS_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = ARGUS_DIR / ".env"
OFFSET_PATH = ARGUS_DIR / "scripts" / "telegram_offset.txt"
LOCK_PATH = ARGUS_DIR / "scripts" / "telegram_key_rotate.lock"

# provider name -> (env var, key pattern)
# Gemini keys come in two formats seen in the wild: the classic AI Studio
# "AIzaSy..." format and a newer "AQ...." format.
PATTERNS = {
    "GEMINI": ("GEMINI_API_KEY", re.compile(r"AIzaSy[A-Za-z0-9_\-]{33}|AQ\.[A-Za-z0-9_\-]{30,80}")),
    "OPENROUTER": ("OPENROUTER_API_KEY", re.compile(r"sk-or-v1-[A-Za-z0-9]{20,}")),
    "GROQ": ("GROQ_API_KEY", re.compile(r"gsk_[A-Za-z0-9]{20,}")),
}


def read_env() -> dict:
    env = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()
    return env


def get_offset() -> int:
    if OFFSET_PATH.exists():
        try:
            return int(OFFSET_PATH.read_text().strip())
        except ValueError:
            return 0
    return 0


def set_offset(offset: int) -> None:
    OFFSET_PATH.write_text(str(offset))


def send_message(token: str, chat_id: str, text: str) -> None:
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except requests.RequestException as e:
        print(f"warn: failed to send telegram confirmation: {e}")


def update_env_var(var_name: str, new_value: str) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    pattern = re.compile(rf"^{re.escape(var_name)}=")
    replaced = False
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f"{var_name}={new_value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{var_name}={new_value}")

    backup_path = ENV_PATH.with_suffix(f".bak.{int(time.time())}")
    backup_path.write_text(ENV_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def restart_app() -> tuple[bool, str]:
    result = subprocess.run(
        ["docker", "compose", "up", "-d", "app"],
        cwd=ARGUS_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    ok = result.returncode == 0
    output = (result.stdout or "") + (result.stderr or "")
    return ok, output.strip()[-500:]


def process_message(text: str, env: dict) -> None:
    for provider, (var_name, pattern) in PATTERNS.items():
        match = pattern.search(text)
        if not match:
            continue
        new_key = match.group(0)
        print(f"detected {provider} key ({len(new_key)} chars) -> updating {var_name}")
        update_env_var(var_name, new_key)
        ok, output = restart_app()
        token = env["TELEGRAM_BOT_TOKEN"]
        chat_id = env["TELEGRAM_CHAT_ID"]
        if ok:
            send_message(token, chat_id, f"✅ {var_name} zaktualizowany, app zrestartowany.")
        else:
            send_message(
                token, chat_id,
                f"⚠️ {var_name} zapisany w .env, ale restart appki nie powiódł się:\n{output}",
            )


def main() -> int:
    lock_file = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("previous run still in progress, skipping")
        return 0

    env = read_env()
    token = env.get("TELEGRAM_BOT_TOKEN")
    expected_chat_id = env.get("TELEGRAM_CHAT_ID")
    if not token or not expected_chat_id:
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing from .env, nothing to do")
        return 0

    offset = get_offset()
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"offset": offset + 1, "timeout": 0},
            timeout=15,
        )
        resp.raise_for_status()
        updates = resp.json().get("result", [])
    except requests.RequestException as e:
        print(f"warn: getUpdates failed: {e}")
        return 0

    max_update_id = offset
    for update in updates:
        max_update_id = max(max_update_id, update["update_id"])
        message = update.get("message") or update.get("edited_message")
        if not message:
            continue
        chat_id = str(message.get("chat", {}).get("id", ""))
        if chat_id != str(expected_chat_id):
            continue  # ignore messages from anyone else
        text = message.get("text", "")
        if text:
            process_message(text, env)

    if max_update_id != offset:
        set_offset(max_update_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
