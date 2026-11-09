import json
from datetime import datetime, timezone
from types import SimpleNamespace

from straznik import report
from straznik.common import load_state, save_state

NOW = datetime(2026, 11, 9, 19, 50, tzinfo=timezone.utc)

JOURNAL = """\
2026-11-09T00:19:17+01:00 vmi sshd[1]: Invalid user web from 88.204.245.66 port 55400
2026-11-09T00:20:17+01:00 vmi sshd[2]: Failed password for root from 88.204.245.66 port 55401 ssh2
2026-11-09T10:00:00+01:00 vmi sshd[3]: Accepted publickey for root from 100.64.1.2 port 5000 ssh2
2026-11-09T11:00:00+01:00 vmi sshd[4]: Accepted publickey for root from 203.0.113.9 port 5001 ssh2
"""
SS = ("tcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:*\n"
      "tcp LISTEN 0 128 0.0.0.0:8096 0.0.0.0:*\n"
      "tcp LISTEN 0 128 0.0.0.0:9999 0.0.0.0:*\n")
FUNNEL = ("https://vmi3495713.tailce2ab5.ts.net (Funnel on)\n"
          "|-- / proxy http://127.0.0.1:8300\n")
APT = ("Listing...\n"
       "openssl/noble-updates,noble-security 3.0.13 amd64 [upgradable from: 3.0.12]\n"
       "byobu/noble-updates 6.11 all [upgradable from: 6.10]\n")
GRAV = ('216.226.78.30 - - [08/Nov/2026:00:52:52 +0000] "GET / HTTP/1.1" 401 726 "-" "Mozilla"\n'
        '85.217.149.41 - - [08/Nov/2026:17:02:12 +0000] "GET /.env HTTP/1.1" 401 726 "-" "Scanner"\n'
        'AH00558: apache2: Could not reliably determine\n')
ALERTS = json.dumps([
    {"scenario": "crowdsecurity/ssh-bf", "source": {"ip": "88.204.245.66"}},
    {"scenario": "crowdsecurity/http-probing", "source": {"ip": "85.217.149.41"}},
])
DECISIONS = json.dumps([
    {"decisions": [{"value": "88.204.245.66", "scenario": "crowdsecurity/ssh-bf"},
                   {"value": "85.217.149.41", "scenario": "crowdsecurity/http-probing"}]},
])


def R(out="", rc=0):
    return SimpleNamespace(returncode=rc, stdout=out, stderr="")


def make_runner(overrides=None, fail=()):
    table = {
        "journalctl": R(JOURNAL), "ss": R(SS), "tailscale": R(FUNNEL),
        "apt": R(APT), "docker-logs": R(GRAV),
        "docker-ps": R("korczaka-grav\nargus-db-1\nnew-thing\n"),
        "decisions": R(DECISIONS), "alerts": R(ALERTS),
    }
    table.update(overrides or {})

    def runner(cmd, timeout=120):
        c = cmd[0]
        if c == "docker":
            key = "docker-logs" if cmd[1] == "logs" else "docker-ps"
        elif c == "cscli":
            key = cmd[1]
        else:
            key = c
        if key in fail or c in fail:
            raise OSError("brak polecenia")
        return table[key]
    return runner


def cfg():
    return {"categories": {"A": [{"container": "argus-db-1"}],
                           "B": [{"container": "korczaka-grav"}], "C": []},
            "allowed_public_ports": ["22/tcp", "8096/tcp", "41641/udp"],
            "allowed_funnel": [{"url": "https://vmi3495713.tailce2ab5.ts.net",
                                "target": "http://127.0.0.1:8300"}]}


def setup(monkeypatch, tmp_path, reboot=False):
    monkeypatch.setattr(report, "load_config", cfg)
    rb = tmp_path / "reboot-required"
    if reboot:
        rb.write_text("")
    monkeypatch.setattr(report, "REBOOT_FILE", str(rb))


def test_collect_full(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path, reboot=True)
    save_state("updates", {"items": [
        {"ts": "2026-11-09T02:00:00+00:00", "container": "a", "result": "updated"},
        {"ts": "2026-11-09T03:00:00+00:00", "container": "b", "result": "rolled_back"},
        {"ts": "2026-11-01T03:00:00+00:00", "container": "old", "result": "failed"}]})
    save_state("trivy", {"scanned_at": "2026-11-08T03:00:00+00:00", "images": {
        "img1": [{"fixed_version": "1.2"}, {"fixed_version": ""}], "img2": []}, "errors": {}})
    save_state("versions", {"results": {
        "korczaka-grav": {"newer": True, "current": "1", "latest": "2"},
        "argus-db-1": {"newer": True, "current": "1", "latest": "2"}}})
    d = report.collect(now=NOW, runner=make_runner())
    assert d["ssh_failed"] == 2
    assert [(l["ip"], l["outside"]) for l in d["ssh_logins"]] == [
        ("100.64.1.2", False), ("203.0.113.9", True)]
    assert d["crowdsec"] == {"blocked": 2, "ssh": 1, "http": 1}
    k = d["korczaka"]
    assert k["requests"] == 2 and k["suspicious"] == 1 and k["blocked"] == 1
    assert len(k["examples"]) == 1 and "85.217.149.41" in k["examples"][0]
    assert d["ports"] == ["9999/tcp"]
    assert d["funnel"] == []
    assert len(d["updates"]) == 2
    assert d["apt_security"] == 1
    assert d["reboot_required"] is True
    assert d["trivy"] == {"scanned_at": "2026-11-08T03:00:00+00:00", "images": {"img1": 1},
                          "errors": 0, "stale": False}
    assert list(d["versions"]) == ["korczaka-grav"]
    assert d["uncategorized"] == ["new-thing"]


def test_collect_missing_trivy_json(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    d = report.collect(now=NOW, runner=make_runner())
    assert d["trivy"] == {"scanned_at": None, "images": {}, "errors": 0, "stale": True}
    assert "Trivy: brak skanu" in report.format_section(d)


def test_collect_sources_independent(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    d = report.collect(now=NOW, runner=make_runner(
        fail=("journalctl", "ss", "cscli", "apt")))
    assert d["ssh_failed"] is None and d["ssh_logins"] is None
    assert d["ports"] is None and d["apt_security"] is None
    assert d["crowdsec"] is None
    assert d["korczaka"]["requests"] == 2
    text = report.format_section(d)
    assert "CrowdSec: brak danych" in text
    assert "brak danych" in text


def test_collect_cscli_nonzero_and_garbage(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    d = report.collect(now=NOW, runner=make_runner({"decisions": R("", 1)}))
    assert d["crowdsec"] is None
    d = report.collect(now=NOW, runner=make_runner({"decisions": R("null"), "alerts": R("{}")}))
    assert d["crowdsec"] == {"blocked": 0, "ssh": 0, "http": 0}


def test_format_section_all_points_present(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path, reboot=True)
    save_state("updates", {"items": [
        {"ts": "2026-11-09T02:00:00+00:00", "container": "a", "result": "updated"},
        {"ts": "2026-11-09T03:00:00+00:00", "container": "b", "result": "rolled_back"}]})
    save_state("trivy", {"scanned_at": "2026-11-08T03:00:00+00:00",
                         "images": {"img1": [{"fixed_version": "1"}]}})
    save_state("versions", {"results": {"korczaka-grav": {"newer": True, "current": "1", "latest": "2"}}})
    text = report.format_section(report.collect(now=NOW, runner=make_runner()))
    assert text.startswith("🛡️ Bezpieczeństwo — ostatnie 24 h")
    for needle in ("SSH:", "Korczaka:", "Porty:", "Funnel:", "Aktualizacje:", "System:",
                   "Trivy (2026-11-08):", "Wersje przypięte:", "Bez kategorii:", "203.0.113.9",
                   "9999/tcp", "zaktualizowano a", "cofnięto b", "restart", "img1",
                   "korczaka-grav", "new-thing"):
        assert needle in text, needle
    assert len(text) < 1500
    assert "*" not in text and "`" not in text


def test_format_section_empty_day_says_brak():
    data = {"ssh_failed": 0, "ssh_logins": [], "crowdsec": {"blocked": 0, "ssh": 0, "http": 0},
            "korczaka": {"requests": 0, "suspicious": 0, "blocked": 0, "examples": []},
            "ports": [], "funnel": [], "updates": [], "apt_security": 0,
            "reboot_required": False,
            "trivy": {"scanned_at": "2026-11-08T03:00:00+00:00", "images": {}},
            "versions": {}, "uncategorized": []}
    text = report.format_section(data)
    assert "brak" in text
    assert "Aktualizacje: brak" in text
    assert "Bez kategorii: brak" in text
    assert report.findings(data) == []


def test_findings_lists_actionables(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path, reboot=True)
    save_state("updates", {"items": [
        {"ts": "2026-11-09T03:00:00+00:00", "container": "b", "result": "rolled_back"}]})
    save_state("trivy", {"scanned_at": "x", "images": {"img1": [{"fixed_version": "1"}]}})
    save_state("versions", {"results": {"korczaka-grav": {"newer": True, "current": "1", "latest": "2"}}})
    f = report.findings(report.collect(now=NOW, runner=make_runner()))
    joined = "\n".join(f)
    for needle in ("203.0.113.9", "9999/tcp", "b", "łat", "restart", "img1",
                   "korczaka-grav", "new-thing"):
        assert needle in joined, needle


def test_findings_empty_no_llm_call(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(report, "llm_comment", lambda f, post=None: calls.append(f))
    clean = {"ssh_logins": [], "ports": [], "funnel": [], "updates": [], "apt_security": 0,
             "reboot_required": False, "trivy": {"images": {}}, "versions": {}, "uncategorized": []}
    monkeypatch.setattr(report, "collect", lambda now=None, runner=None: clean)
    monkeypatch.setattr(report, "format_section", lambda d: "sekcja")
    assert report.daily(now=NOW, runner=make_runner()) == "sekcja"
    assert calls == []


def test_llm_comment_request(monkeypatch, tmp_path):
    env = tmp_path / "litellm.env"
    env.write_text("LITELLM_MASTER_KEY=sk-secret\n")
    monkeypatch.setattr(report, "LITELLM_ENV", str(env))
    seen = {}

    def post(url, body, headers, timeout):
        seen.update(url=url, body=body, headers=headers, timeout=timeout)
        return {"choices": [{"message": {"content": "  Zrób X.  "}}]}
    assert report.llm_comment(["ustalenie A"], post=post) == "Zrób X."
    assert seen["url"] == "http://100.71.197.18:4000/v1/chat/completions"
    assert seen["body"]["model"] == "straznik" and seen["body"]["temperature"] == 0.2
    assert seen["headers"]["Authorization"] == "Bearer sk-secret"
    assert seen["timeout"] == 240
    assert "ustalenie A" in seen["body"]["messages"][0]["content"]


def test_llm_failure_section_without_comment(monkeypatch, tmp_path):
    env = tmp_path / "litellm.env"
    env.write_text("LITELLM_MASTER_KEY=k\n")
    monkeypatch.setattr(report, "LITELLM_ENV", str(env))

    def boom(*a, **k):
        raise OSError("Mac nie odpowiada")
    assert report.llm_comment(["x"], post=boom) is None
    monkeypatch.setattr(report, "LITELLM_ENV", str(tmp_path / "nie-ma"))
    assert report.llm_comment(["x"], post=lambda *a, **k: {}) is None
    monkeypatch.setattr(report, "LITELLM_ENV", str(env))
    assert report.llm_comment(["x"], post=lambda *a, **k: {"zle": 1}) is None


def test_daily_writes_section_file(monkeypatch, tmp_path, state_dir):
    setup(monkeypatch, tmp_path)
    monkeypatch.setattr(report, "llm_comment", lambda f, post=None: "Zmień klucze.")
    text = report.daily(now=NOW, runner=make_runner())
    assert text.endswith("\n💬 Zmień klucze.")
    assert (state_dir / "section.txt").read_text(encoding="utf-8") == text


def test_daily_survives_total_failure(monkeypatch, tmp_path, state_dir):
    setup(monkeypatch, tmp_path)
    monkeypatch.setattr(report, "llm_comment", lambda f, post=None: None)
    text = report.daily(now=NOW, runner=make_runner(
        fail=("journalctl", "ss", "tailscale", "cscli", "apt", "docker")))
    assert "brak danych" in text
    assert (state_dir / "section.txt").exists()


def test_cscli_lists_unlimited(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    seen = []
    base = make_runner()

    def runner(cmd, timeout=120):
        if cmd[0] == "cscli":
            seen.append(cmd)
        return base(cmd, timeout)
    report.collect(now=NOW, runner=runner)
    assert seen and all(c[2:4] == ["list", "-l"] or "-l" in c for c in seen)
    assert all(c[c.index("-l") + 1] == "0" for c in seen)


def test_trivy_stale_missing_errors(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    save_state("trivy", {"scanned_at": "2026-10-20T03:00:00+00:00", "images": {},
                         "errors": {"a": "x", "b": "y"}})
    d = report.collect(now=NOW, runner=make_runner())
    text = report.format_section(d)
    assert "Trivy: skan starszy niż 8 dni (2026-10-20)" in text
    assert "nieudane skany obrazów 2" in text
    f = "\n".join(report.findings(d))
    assert "starszy niż 8 dni" in f and "nie objął obrazów: 2" in f


def test_versions_errors_shown(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    save_state("versions", {"results": {}, "errors": {"litellm": "x", "m": "y", "z": "w"}})
    d = report.collect(now=NOW, runner=make_runner())
    assert "błędy sprawdzania 3" in report.format_section(d)


def test_watch_line_and_stale_finding(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    d = report.collect(now=NOW, runner=make_runner())
    assert "Kontrola co 5 min: brak udanego uruchomienia" in report.format_section(d)
    assert any("Kontrola co 5 min" in x for x in report.findings(d))
    save_state("watch", {"last_run": "2026-11-09T19:47:00+00:00"})
    d = report.collect(now=NOW, runner=make_runner())
    assert "Kontrola co 5 min: ostatnia udana " in report.format_section(d)
    assert not any("Kontrola co 5 min" in x for x in report.findings(d))
    save_state("watch", {"last_run": "2026-11-09T18:00:00+00:00"})
    assert report.collect(now=NOW, runner=make_runner())["watch"]["stale"] is True


def test_daily_always_writes_section(monkeypatch, tmp_path, state_dir):
    def boom(**k):
        raise ValueError("x")
    monkeypatch.setattr(report, "collect", boom)
    text = report.daily(now=NOW, runner=make_runner())
    assert text == "🛡️ Bezpieczeństwo: błąd raportu Strażnika (ValueError)"
    assert (state_dir / "section.txt").read_text(encoding="utf-8") == text


def test_length_caps(monkeypatch, tmp_path, state_dir):
    env = tmp_path / "litellm.env"
    env.write_text("LITELLM_MASTER_KEY=k\n")
    monkeypatch.setattr(report, "LITELLM_ENV", str(env))
    out = report.llm_comment(["x"], post=lambda *a, **k: {"choices": [{"message": {"content": "a" * 900}}]})
    assert len(out) == 500 and out.endswith("…")
    setup(monkeypatch, tmp_path)
    long = ('85.217.149.41 - - [08/Nov/2026:17:02:12 +0000] "GET /' + "x" * 400 + ' HTTP/1.1" 401 7\n')
    d = report.collect(now=NOW, runner=make_runner({"docker-logs": SimpleNamespace(
        returncode=0, stdout=long, stderr="")}))
    assert d["korczaka"]["examples"] and len(d["korczaka"]["examples"][0]) == 160
    monkeypatch.setattr(report, "format_section", lambda d: "s" * 3000)
    monkeypatch.setattr(report, "llm_comment", lambda f, post=None: None)
    assert len(report.daily(now=NOW, runner=make_runner())) == 1800


def test_ssh_fail_regex_sshd_session():
    assert report._SSH_FAIL.search("vmi sshd-session[12]: Failed password for root from 1.2.3.4")
