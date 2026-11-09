"""Kontrola co 5 minut: logowania SSH, porty publiczne, Funnel, CrowdSec."""
import ipaddress
import re
import sys
from datetime import datetime, timedelta, timezone

from straznik.common import ALERT_INTERVAL, alert, load_config, load_state, run, save_state

_TS_V4 = ipaddress.ip_network("100.64.0.0/10")
_TS_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")
_DOCKER = ipaddress.ip_network("172.16.0.0/12")
_ACCEPTED = re.compile(
    r"^(\S+)\s+\S+\s+sshd(?:-session)?(?:\[\d+\])?:\s+Accepted (\S+) for (\S+) from (\S+) port \d+"
)
_FUNNEL_HEAD = re.compile(r"^(https://\S+)\s+\(Funnel on\)")
_FUNNEL_PROXY = re.compile(r"^\|--\s+\S+\s+proxy\s+(\S+)")
SERVICES = ("crowdsec", "crowdsec-firewall-bouncer")


def is_tailscale(ip):
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    return addr in (_TS_V4 if addr.version == 4 else _TS_V6)


def parse_ssh_accepted(journal_text):
    out = []
    for line in journal_text.splitlines():
        m = _ACCEPTED.match(line.strip())
        if m:
            out.append({"ts": m.group(1), "method": m.group(2), "user": m.group(3), "ip": m.group(4)})
    return out


def parse_public_listeners(ss_text):
    ports = set()
    for line in ss_text.splitlines():
        f = line.split()
        if len(f) < 5 or f[0] not in ("tcp", "udp"):
            continue
        host, _, port = f[4].rpartition(":")
        host = host.strip("[]")
        if "%" in host or not port.isdigit():
            continue
        if host not in ("*", ""):
            try:
                addr = ipaddress.ip_address(host)
            except ValueError:
                continue
            if addr.is_loopback or is_tailscale(host) or (addr.version == 4 and addr in _DOCKER):
                continue
        ports.add(f"{port}/{f[0]}")
    return ports


def parse_funnel(status_text):
    """Każdy handler pod nagłówkiem (Funnel on) -> {url, target}; nie-proxy dają target typu "path /srv"."""
    out, url, handlers = [], None, 0

    def close():
        if url and not handlers:
            out.append({"url": url, "target": ""})

    for raw in status_text.splitlines():
        line = raw.strip()
        m = _FUNNEL_HEAD.match(line)
        if m:
            close()
            url, handlers = m.group(1), 0
            continue
        if url is None:
            continue
        if not line:
            close()
            url = None
        elif line.startswith(("|", "+", "`")):
            body = line.lstrip("|+`- ").strip()
            parts = body.split(None, 1)
            rest = parts[1] if len(parts) > 1 else body
            m = _FUNNEL_PROXY.match(line)
            out.append({"url": url, "target": m.group(1) if m else rest})
            handlers += 1
        elif line.startswith("https://"):
            close()
            url = None
    close()
    return out


def _out(runner, cmd):
    r = runner(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} zwróciło kod {r.returncode}")
    return r.stdout


def _handled(key, now, sent_ok):
    """True gdy alarm poszedł albo był już wysłany w oknie deduplikacji."""
    if sent_ok:
        return True
    try:
        return now - datetime.fromisoformat(load_state("alerts")[key]) < ALERT_INTERVAL
    except (KeyError, TypeError, ValueError):
        return False


def _check_ssh(now, runner, alert_fn, sent):
    """Zwraca True, gdy okno zostało w pełni obsłużone (można przesunąć last_run)."""
    last = load_state("watch").get("last_run")
    try:
        since = datetime.fromisoformat(last)
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        since = now - timedelta(minutes=10)
    since_s = since.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    out = _out(runner, ["journalctl", "-u", "ssh", "--since", since_s, "-o", "short-iso"])
    complete = True
    for e in parse_ssh_accepted(out):
        if is_tailscale(e["ip"]):
            continue
        key = f"ssh:{e['ip']}"
        text = (f"🚨 Logowanie SSH spoza Tailscale: {e['user']} z {e['ip']} o {e['ts']}. "
                "Jeśli to nie Ty — natychmiast zmień klucze.")
        ok = alert_fn(key, text, now=now)
        if ok:
            sent.append(key)
        elif not _handled(key, now, ok):
            complete = False
    return complete


def _check_ports(cfg, now, runner, alert_fn, sent):
    found = parse_public_listeners(_out(runner, ["ss", "-tulnH"]))
    for port in sorted(found - set(cfg.get("allowed_public_ports", []))):
        text = f"🚨 Nowy publiczny port nasłuchujący: {port}. Sprawdź, co go otworzyło."
        if alert_fn(f"port:{port}", text, now=now):
            sent.append(f"port:{port}")


def _check_funnel(cfg, now, runner, alert_fn, sent):
    allowed = {(a["url"], a["target"]) for a in cfg.get("allowed_funnel", [])}
    unknown = {}
    for e in parse_funnel(_out(runner, ["tailscale", "funnel", "status"])):
        if (e["url"], e["target"]) not in allowed:
            unknown.setdefault(e["url"], []).append(e["target"] or "(brak handlera)")
    for url, targets in unknown.items():
        key = f"funnel:{url}"
        text = f"🚨 Nieznany Funnel Tailscale: {url} → {', '.join(targets)}. Usługa jest widoczna w internecie."
        if alert_fn(key, text, now=now):
            sent.append(key)


def _check_crowdsec(now, runner, alert_fn, sent):
    for svc in SERVICES:
        state = runner(["systemctl", "is-active", svc]).stdout.strip()
        if state != "active":
            key = f"crowdsec:{svc}"
            text = f"⚠️ Usługa {svc} nie działa (stan: {state or 'brak'})."
            if alert_fn(key, text, now=now):
                sent.append(key)


def check(now=None, runner=run, alert_fn=alert):
    now = now or datetime.now(timezone.utc)
    sent = []
    results = {}

    def guarded(name, fn):
        try:
            results[name] = fn()
        except Exception as e:  # jedna kontrola nie może zatrzymać pozostałych
            results[name] = False
            print(f"watch: błąd kontroli {name}: {e!r}", file=sys.stderr)
            key = f"watch:error:{name}"
            if alert_fn(key, f"⚠️ Strażnik: kontrola {name} nie działa: {str(e)[:150]}", now=now):
                sent.append(key)

    guarded("ssh", lambda: _check_ssh(now, runner, alert_fn, sent))
    guarded("ports", lambda: _check_ports(load_config(), now, runner, alert_fn, sent))
    guarded("funnel", lambda: _check_funnel(load_config(), now, runner, alert_fn, sent))
    guarded("crowdsec", lambda: _check_crowdsec(now, runner, alert_fn, sent))
    if results.get("ssh"):
        state = load_state("watch")
        state["last_run"] = now.isoformat()
        save_state("watch", state)
    return sent


if __name__ == "__main__":
    check()
