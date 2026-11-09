"""Wspólne narzędzia Strażnika: uruchamianie poleceń, stan, konfiguracja, alarmy."""
import json
import os
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ARGUS_ENV = "/root/argus/.env"
ALERT_INTERVAL = timedelta(hours=6)

STATE_DIR = Path(os.getenv("STRAZNIK_STATE_DIR", "/var/lib/straznik"))


def _state_dir():
    # czytane przy każdym wywołaniu, żeby testy mogły podmienić zmienną środowiskową
    return Path(os.getenv("STRAZNIK_STATE_DIR", str(STATE_DIR)))


def run(cmd, timeout=120):
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)


def load_state(name):
    try:
        data = json.loads((_state_dir() / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(name, data):
    d = _state_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{name}.json.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, d / f"{name}.json")


def load_config(path=None):
    p = Path(path) if path else Path(__file__).resolve().parent.parent / "containers.yaml"
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_env_value(path, key):
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == key:
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            return v
    return None


def send_telegram(text, token=None, chat=None):
    try:
        token = token or read_env_value(ARGUS_ENV, "TELEGRAM_BOT_TOKEN")
        chat = chat or read_env_value(ARGUS_ENV, "TELEGRAM_CHAT_ID")
        if not token or not chat:
            return False
        body = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception:
        return False


def alert(key, text, now=None, sender=send_telegram):
    now = now or datetime.now(timezone.utc)
    alerts = load_state("alerts")
    last = alerts.get(key)
    if last:
        try:
            if now - datetime.fromisoformat(last) < ALERT_INTERVAL:
                return False
        except ValueError:
            pass
    if not sender(text):
        return False
    alerts[key] = now.isoformat()
    save_state("alerts", alerts)
    return True
