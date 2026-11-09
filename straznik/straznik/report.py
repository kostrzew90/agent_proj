"""Raport dzienny: sekcja bezpieczeństwa dla Telegrama + krótki komentarz modelu."""
import json
import os
import re
import urllib.request
from datetime import datetime, timedelta, timezone

from straznik.common import _state_dir, load_config, load_state, read_env_value, run
from straznik.watch import is_tailscale, parse_funnel, parse_public_listeners, parse_ssh_accepted

REBOOT_FILE = "/var/run/reboot-required"
LITELLM_ENV = "/root/litellm/.env"
LITELLM_URL = "http://100.71.197.18:4000/v1/chat/completions"
KORCZAKA = "korczaka-grav"
HEADER = "🛡️ Bezpieczeństwo — ostatnie 24 h"
COMMENT_MAX = 500
EXAMPLE_MAX = 160
SECTION_MAX = 1800
TRIVY_STALE = timedelta(days=8)
WATCH_STALE = timedelta(minutes=30)
PROMPT = ("Jesteś asystentem bezpieczeństwa serwera. Na podstawie ustaleń napisz po polsku "
          "2-3 krótkie zdania: co jest najważniejsze i co konkretnie zrobić. Bez wstępów.")

_SSH_FAIL = re.compile(r"sshd(?:-session)?(?:\[\d+\])?:\s+(?:Failed|Invalid user)\b")
_ACCESS = re.compile(r'^(\S+) \S+ \S+ \[[^\]]+\] "')


def _ok(runner, cmd):
    r = runner(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} kod {r.returncode}")
    return r.stdout


def _trunc(text, n):
    return text if len(text) <= n else text[:n - 1] + "…"


def _parse_ts(value):
    try:
        ts = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _local_hhmm(ts):
    try:
        from zoneinfo import ZoneInfo
        return ts.astimezone(ZoneInfo("Europe/Warsaw")).strftime("%H:%M")
    except Exception:
        return ts.astimezone(timezone.utc).strftime("%H:%M") + " UTC"


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


def _json_list(text):
    try:
        data = json.loads(text)
    except ValueError:
        return []
    return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []


def _scenario_kind(scenario):
    s = (scenario or "").lower()
    if "ssh" in s:
        return "ssh"
    if any(w in s for w in ("http", "apache", "web")):
        return "http"
    return None


def _crowdsec(runner):
    """(statystyki, {ip: rodzaj} decyzji, [(ip, rodzaj)] alertów) albo None gdy cscli niedostępne."""
    dec = _json_list(_ok(runner, ["cscli", "decisions", "list", "-l", "0", "-o", "json"]))
    alerts = _json_list(_ok(runner, ["cscli", "alerts", "list", "-l", "0", "--since", "24h", "-o", "json"]))
    flat = []
    for item in dec:
        sub = item.get("decisions")
        if isinstance(sub, list):
            for x in sub:
                if isinstance(x, dict):
                    flat.append(dict(x, scenario=x.get("scenario") or item.get("scenario")))
        else:
            flat.append(item)
    blocked = {}
    for x in flat:
        if x.get("value"):
            blocked.setdefault(str(x["value"]), _scenario_kind(x.get("scenario")))
    kinds = list(blocked.values())
    stats = {"blocked": len(blocked), "ssh": kinds.count("ssh"), "http": kinds.count("http")}
    alert_ips = []
    for a in alerts:
        src = a.get("source") if isinstance(a.get("source"), dict) else {}
        alert_ips.append((src.get("ip"), _scenario_kind(a.get("scenario"))))
    return stats, blocked, alert_ips


def _korczaka(runner, cs):
    out = {"requests": None, "suspicious": None, "blocked": None, "examples": []}
    lines = []
    try:
        r = runner(["docker", "logs", "--since", "24h", KORCZAKA])
        if r.returncode == 0:
            lines = ((r.stdout or "") + (r.stderr or "")).splitlines()
            out["requests"] = sum(1 for ln in lines if _ACCESS.match(ln))
    except Exception:
        pass
    if cs:
        _, blocked, alert_ips = cs
        bad = {ip for ip, k in alert_ips if ip and k == "http"}
        bad_blocked = {ip for ip, k in blocked.items() if k == "http"}
        out["suspicious"] = sum(1 for _, k in alert_ips if k == "http")
        out["blocked"] = len(bad_blocked)
        for ln in lines:
            m = _ACCESS.match(ln)
            if m and m.group(1) in bad | bad_blocked and len(out["examples"]) < 3:
                out["examples"].append(_trunc(ln, EXAMPLE_MAX))
    return out


def _updates(now):
    cutoff = now - timedelta(hours=24)
    out = []
    for it in load_state("updates").get("items", []):
        try:
            ts = datetime.fromisoformat(it["ts"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except (KeyError, TypeError, ValueError):
            continue
        if ts >= cutoff:
            out.append(it)
    return out


def _apt_security(runner):
    n = 0
    for line in _ok(runner, ["apt", "list", "--upgradable"]).splitlines():
        head = line.split(None, 1)[0] if line.strip() else ""
        if "/" in head and "-security" in head.split("/", 1)[1]:
            n += 1
    return n


def _trivy(now):
    t = load_state("trivy")
    images = {}
    for img, vulns in (t.get("images") or {}).items():
        n = sum(1 for v in vulns if isinstance(v, dict) and v.get("fixed_version"))
        if n:
            images[img] = n
    at = _parse_ts(t.get("scanned_at"))
    errors = t.get("errors")
    return {"scanned_at": t.get("scanned_at"), "images": images,
            "errors": len(errors) if isinstance(errors, dict) else 0,
            "stale": at is None or now - at > TRIVY_STALE}


def collect(now=None, runner=run):
    now = now or datetime.now(timezone.utc)
    d = {}
    since = (now - timedelta(hours=24)).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    journal = _safe(lambda: _ok(runner, ["journalctl", "-u", "ssh", "--since", since, "-o", "short-iso"]))
    d["ssh_failed"] = None if journal is None else sum(1 for ln in journal.splitlines() if _SSH_FAIL.search(ln))
    d["ssh_logins"] = None if journal is None else [
        dict(e, outside=not is_tailscale(e["ip"])) for e in parse_ssh_accepted(journal)]
    cs = _safe(lambda: _crowdsec(runner))
    d["crowdsec"] = cs[0] if cs else None
    d["korczaka"] = _korczaka(runner, cs)
    cfg = _safe(load_config) or {}
    allowed_ports = set(cfg.get("allowed_public_ports", []))
    allowed_funnel = {(a["url"], a["target"]) for a in cfg.get("allowed_funnel", [])}
    d["ports"] = _safe(lambda: sorted(
        parse_public_listeners(_ok(runner, ["ss", "-tulnH"])) - allowed_ports))
    d["funnel"] = _safe(lambda: [
        f"{e['url']} → {e['target'] or '(brak handlera)'}"
        for e in parse_funnel(_ok(runner, ["tailscale", "funnel", "status"]))
        if (e["url"], e["target"]) not in allowed_funnel])
    d["updates"] = _safe(lambda: _updates(now)) or []
    d["apt_security"] = _safe(lambda: _apt_security(runner))
    d["reboot_required"] = os.path.exists(REBOOT_FILE)
    d["trivy"] = _safe(lambda: _trivy(now)) or {"scanned_at": None, "images": {}, "errors": 0, "stale": True}
    last = _parse_ts(load_state("watch").get("last_run"))
    d["watch"] = {"last_run": last.isoformat() if last else None,
                  "stale": last is None or now - last > WATCH_STALE}
    verr = load_state("versions").get("errors")
    d["versions_errors"] = len(verr) if isinstance(verr, dict) else 0
    b = {c.get("container") for c in (cfg.get("categories", {}).get("B") or [])}
    res = load_state("versions").get("results") or {}
    d["versions"] = {k: v for k, v in res.items()
                     if k in b and isinstance(v, dict) and v.get("newer")}
    known = {c.get("container") for cat in (cfg.get("categories") or {}).values() for c in (cat or [])}
    ps = _safe(lambda: _ok(runner, ["docker", "ps", "--format", "{{.Names}}"]))
    d["uncategorized"] = None if ps is None else sorted(
        n for n in ps.split() if n not in known)
    return d


def _cap(items, n):
    items = list(items)
    extra = f" (+{len(items) - n})" if len(items) > n else ""
    return ", ".join(items[:n]) + extra


def format_section(data):
    g = data.get
    L = [HEADER]
    cs = g("crowdsec")
    if g("ssh_failed") is None:
        ssh = "SSH: brak danych"
    else:
        ssh = f"SSH: nieudane próby {g('ssh_failed')}"
        ssh += f", zablokowane adresy {cs['ssh']}" if cs else ""
        logins = g("ssh_logins") or []
        ssh += "; udane logowania: " + (_cap(
            (f"{e['user']} z {e['ip']}" + (" ⚠️ spoza Tailscale" if e.get("outside") else "")
             for e in logins), 5) if logins else "brak")
    L.append(ssh)
    L.append("CrowdSec: " + (f"zablokowane adresy {cs['blocked']} (SSH {cs['ssh']}, WWW {cs['http']})"
                            if cs else "brak danych"))
    k = g("korczaka") or {}
    if k.get("requests") is None:
        line = "Korczaka: brak danych"
    else:
        line = f"Korczaka: zapytań {k['requests']}"
        line += (f", podejrzanych {k['suspicious']}, zablokowanych {k['blocked']}"
                 if k.get("suspicious") is not None else ", podejrzane: brak danych")
    L.append(line)
    for ex in k.get("examples") or []:
        L.append("  • " + ex)
    ports, funnel = g("ports"), g("funnel")
    L.append("Porty: " + ("brak danych" if ports is None else
                          "poza listą " + _cap(ports, 5) if ports else "tylko dozwolone"))
    L.append("Funnel: " + ("brak danych" if funnel is None else
                           "poza listą " + _cap(funnel, 3) if funnel else "tylko dozwolony"))
    ups = g("updates") or []
    parts = []
    for res, label in (("updated", "zaktualizowano"), ("rolled_back", "cofnięto"), ("failed", "nie powiodło się")):
        names = [u.get("container", "?") for u in ups if u.get("result") == res]
        if names:
            parts.append(f"{label} {_cap(names, 5)}")
    L.append("Aktualizacje: " + ("; ".join(parts) if parts else "brak"))
    apt = g("apt_security")
    L.append("System: łatki bezpieczeństwa " + ("brak danych" if apt is None else str(apt))
             + ("; wymagany restart serwera" if g("reboot_required") else "; restart niepotrzebny"))
    tr = g("trivy") or {}
    if not tr.get("scanned_at"):
        L.append("Trivy: brak skanu")
    else:
        date = str(tr["scanned_at"])[:10]
        imgs = tr.get("images") or {}
        if tr.get("stale"):
            line = f"Trivy: skan starszy niż 8 dni ({date})"
        else:
            line = f"Trivy ({date}): " + (_cap((f"{i} {n}" for i, n in imgs.items()), 5) if imgs
                                          else "brak dziur z poprawką")
        if tr.get("errors"):
            line += f"; nieudane skany obrazów {tr['errors']}"
        L.append(line)
    vs = g("versions") or {}
    line = "Wersje przypięte: " + (_cap((f"{c} {v.get('current')} → {v.get('latest')}"
                                       for c, v in vs.items()), 5) if vs else "brak nowszych")
    if g("versions_errors"):
        line += f"; błędy sprawdzania {g('versions_errors')}"
    L.append(line)
    w = g("watch")
    if w is not None:
        last = _parse_ts(w.get("last_run"))
        L.append("Kontrola co 5 min: " + (f"ostatnia udana {_local_hhmm(last)}" if last else "brak udanego uruchomienia"))
    unc = g("uncategorized")
    L.append("Bez kategorii: " + ("brak danych" if unc is None else _cap(unc, 5) if unc else "brak"))
    return "\n".join(L)


def findings(data):
    g = data.get
    out = []
    for e in g("ssh_logins") or []:
        if e.get("outside"):
            out.append(f"Udane logowanie SSH spoza Tailscale: {e['user']} z {e['ip']}")
    out += [f"Nowy publiczny port: {p}" for p in g("ports") or []]
    out += [f"Nieznany wpis Funnel: {f}" for f in g("funnel") or []]
    for u in g("updates") or []:
        if u.get("result") in ("rolled_back", "failed"):
            out.append(f"Aktualizacja kontenera {u.get('container')} nieudana ({u.get('result')})")
    if g("apt_security"):
        out.append(f"Czekają łatki bezpieczeństwa systemu: {g('apt_security')}")
    if g("reboot_required"):
        out.append("Serwer wymaga restartu")
    tr = g("trivy") or {}
    if tr.get("stale"):
        out.append("Skan Trivy brakuje albo jest starszy niż 8 dni")
    if tr.get("errors"):
        out.append(f"Skan Trivy nie objął obrazów: {tr['errors']}")
    for img, n in (tr.get("images") or {}).items():
        out.append(f"Dziury z dostępną poprawką w obrazie {img}: {n}")
    if g("versions_errors"):
        out.append(f"Nie udało się sprawdzić wersji kontenerów: {g('versions_errors')}")
    if (g("watch") or {}).get("stale"):
        out.append("Kontrola co 5 min nie przeszła pomyślnie od ponad 30 minut (albo wcale)")
    for c, v in (g("versions") or {}).items():
        out.append(f"Nowsza wersja kontenera {c}: {v.get('current')} → {v.get('latest')}")
    if g("uncategorized"):
        out.append("Kontenery bez kategorii: " + ", ".join(g("uncategorized")))
    return out


def urlopen_json_post(url, body, headers, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def llm_comment(findings, post=urlopen_json_post):
    try:
        key = read_env_value(LITELLM_ENV, "LITELLM_MASTER_KEY")
        if not key:
            return None
        body = {"model": "straznik", "temperature": 0.2, "messages": [
            {"role": "user", "content": PROMPT + "\n\n" + "\n".join(f"- {f}" for f in findings)}]}
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        resp = post(LITELLM_URL, body, headers, 240)
        text = resp["choices"][0]["message"]["content"].strip()
        return _trunc(text, COMMENT_MAX) if text else None
    except Exception:
        return None


def daily(now=None, runner=run):
    try:
        data = collect(now=now, runner=runner)
        text = format_section(data)
        items = findings(data)
        comment = llm_comment(items) if items else None
        if comment:
            text += "\n💬 " + comment
        text = _trunc(text, SECTION_MAX)
    except Exception as e:
        text = f"🛡️ Bezpieczeństwo: błąd raportu Strażnika ({type(e).__name__})"
    d = _state_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / ".section.txt.tmp"
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, d / "section.txt")
    return text


if __name__ == "__main__":
    daily()
