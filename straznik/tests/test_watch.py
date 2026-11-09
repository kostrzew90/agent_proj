import subprocess
from datetime import datetime, timezone

from straznik import watch

SS = """udp UNCONN 0      0                                127.0.0.54:53    0.0.0.0:*
udp UNCONN 0      0                             127.0.0.53%lo:53    0.0.0.0:*
udp UNCONN 0      0                                   0.0.0.0:41641 0.0.0.0:*
udp UNCONN 0      0                                      [::]:41641    [::]:*
tcp LISTEN 0      4096                          100.71.197.18:8080  0.0.0.0:*
tcp LISTEN 0      4096                                0.0.0.0:22    0.0.0.0:*
tcp LISTEN 0      4096                          127.0.0.53%lo:53    0.0.0.0:*
tcp LISTEN 0      4096                              127.0.0.1:5433  0.0.0.0:*
tcp LISTEN 0      4096               100.71.197.18%tailscale0:36884 0.0.0.0:*
tcp LISTEN 0      4096                                0.0.0.0:8096  0.0.0.0:*
tcp LISTEN 0      4096                              127.0.0.1:8300  0.0.0.0:*
tcp LISTEN 0      4096   [fd7a:115c:a1e0::35:c513]%tailscale0:40124    [::]:*
tcp LISTEN 0      4096                                   [::]:22       [::]:*
tcp LISTEN 0      4096                              172.18.0.1:9999  0.0.0.0:*
"""

JOURNAL_TS = """2026-11-09T00:16:53+01:00 vmi3495713 sshd[76257]: Accepted publickey for root from 100.125.179.91 port 44105 ssh2: ED25519 SHA256:XXX
2026-11-09T00:19:17+01:00 vmi3495713 sshd[85364]: Invalid user web from 88.204.245.66 port 55400
"""
JOURNAL_PUBLIC = JOURNAL_TS + """2026-11-09T00:20:59+01:00 vmi3495713 sshd[91329]: Accepted publickey for root from 88.204.245.66 port 37217 ssh2: ED25519 SHA256:XXX
"""

FUNNEL_OK = """
# Funnel on:
#     - https://vmi3495713.tailce2ab5.ts.net

https://vmi3495713.tailce2ab5.ts.net (Funnel on)
|-- / proxy http://127.0.0.1:8300

"""
FUNNEL_BAD = FUNNEL_OK + """https://other.ts.net (Funnel on)
|-- / proxy http://127.0.0.1:9000
"""

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def make_runner(ss=SS, journal=JOURNAL_TS, funnel=FUNNEL_OK, services=None, rc=None):
    services = services or {}
    rc = rc or {}
    calls = []

    def runner(cmd, timeout=120):
        calls.append(cmd)
        out = ""
        if cmd[0] == "ss":
            out = ss
        elif cmd[0] == "journalctl":
            out = journal
        elif cmd[0] == "tailscale":
            out = funnel
        elif cmd[0] == "systemctl":
            out = services.get(cmd[-1], "active") + "\n"
        return subprocess.CompletedProcess(cmd, rc.get(cmd[0], 0), out, "")

    runner.calls = calls
    return runner


def run_check(runner):
    sent = []

    def alert_fn(key, text, now=None, **kw):
        sent.append((key, text))
        return True

    keys = watch.check(now=NOW, runner=runner, alert_fn=alert_fn)
    return keys, sent


def test_public_listeners_ignores_tailscale_and_local():
    assert watch.parse_public_listeners(SS) == {"22/tcp", "8096/tcp", "41641/udp"}


def test_is_tailscale():
    assert watch.is_tailscale("100.125.179.91")
    assert watch.is_tailscale("fd7a:115c:a1e0::35:c513")
    assert not watch.is_tailscale("88.204.245.66")
    assert not watch.is_tailscale("not-an-ip")


def test_parse_ssh_accepted():
    r = watch.parse_ssh_accepted(JOURNAL_PUBLIC)
    assert [(x["user"], x["ip"], x["method"]) for x in r] == [
        ("root", "100.125.179.91", "publickey"),
        ("root", "88.204.245.66", "publickey"),
    ]
    assert r[0]["ts"] == "2026-11-09T00:16:53+01:00"


def test_parse_funnel():
    assert watch.parse_funnel(FUNNEL_BAD) == [
        {"url": "https://vmi3495713.tailce2ab5.ts.net", "target": "http://127.0.0.1:8300"},
        {"url": "https://other.ts.net", "target": "http://127.0.0.1:9000"},
    ]


def test_check_quiet_when_all_ok():
    keys, sent = run_check(make_runner())
    assert keys == [] and sent == []


def test_check_alerts_new_public_port():
    keys, _ = run_check(make_runner(ss=SS + "tcp LISTEN 0 4096 0.0.0.0:18999 0.0.0.0:*\n"))
    assert keys == ["port:18999/tcp"]


def test_check_ssh_tailscale_login_silent():
    keys, _ = run_check(make_runner(journal=JOURNAL_TS))
    assert keys == []


def test_check_ssh_public_login_alerts():
    keys, sent = run_check(make_runner(journal=JOURNAL_PUBLIC))
    assert keys == ["ssh:88.204.245.66"]
    assert "Logowanie SSH spoza Tailscale: root z 88.204.245.66" in sent[0][1]


def test_check_funnel_unknown_alerts():
    keys, _ = run_check(make_runner(funnel=FUNNEL_BAD))
    assert keys == ["funnel:https://other.ts.net"]


def test_check_crowdsec_down_alerts():
    keys, _ = run_check(make_runner(services={"crowdsec": "inactive"}))
    assert keys == ["crowdsec:crowdsec"]


def test_check_one_failing_command_does_not_stop_others():
    base = make_runner(services={"crowdsec-firewall-bouncer": "failed"})

    def runner(cmd, timeout=120):
        if cmd[0] == "journalctl":
            raise FileNotFoundError("journalctl")
        return base(cmd, timeout)

    keys, _ = run_check(runner)
    assert keys == ["watch:error:ssh", "crowdsec:crowdsec-firewall-bouncer"]


def test_check_saves_last_run_and_uses_it():
    from straznik.common import load_state
    runner = make_runner()
    run_check(runner)
    assert load_state("watch")["last_run"] == NOW.isoformat()
    runner2 = make_runner()
    run_check(runner2)
    j = [c for c in runner2.calls if c[0] == "journalctl"][0]
    assert "2026-11-09 12:00:00 UTC" in j


def test_failed_journal_does_not_advance_last_run():
    from straznik.common import load_state
    keys, sent = run_check(make_runner(journal="", rc={"journalctl": 1}))
    assert keys == ["watch:error:ssh"]
    assert "kontrola ssh nie działa" in sent[0][1]
    assert "last_run" not in load_state("watch")


def test_ssh_alert_not_sent_does_not_advance_last_run():
    from straznik.common import load_state
    runner = make_runner(journal=JOURNAL_PUBLIC)
    watch.check(now=NOW, runner=runner, alert_fn=lambda *a, **k: False)
    assert "last_run" not in load_state("watch")


def test_ssh_deduped_alert_advances_last_run():
    from straznik.common import load_state, save_state
    save_state("alerts", {"ssh:88.204.245.66": NOW.isoformat()})
    runner = make_runner(journal=JOURNAL_PUBLIC)
    watch.check(now=NOW, runner=runner, alert_fn=lambda *a, **k: False)
    assert load_state("watch")["last_run"] == NOW.isoformat()


def test_ss_nonzero_alerts_check_error():
    keys, _ = run_check(make_runner(ss="", rc={"ss": 2}))
    assert keys == ["watch:error:ports"]


def test_funnel_nonzero_alerts_check_error():
    keys, _ = run_check(make_runner(funnel="", rc={"tailscale": 1}))
    assert keys == ["watch:error:funnel"]


def test_exception_in_check_alerts_error():
    base = make_runner()

    def runner(cmd, timeout=120):
        if cmd[0] == "systemctl":
            raise FileNotFoundError("systemctl")
        return base(cmd, timeout)

    keys, _ = run_check(runner)
    assert keys == ["watch:error:crowdsec"]


FUNNEL_FILES = """https://vmi3495713.tailce2ab5.ts.net (Funnel on)
|-- / proxy http://127.0.0.1:8300
|-- /files path /srv/secret

"""


def test_funnel_non_proxy_handler_alerts():
    entries = watch.parse_funnel(FUNNEL_FILES)
    assert {"url": "https://vmi3495713.tailce2ab5.ts.net", "target": "path /srv/secret"} in entries
    keys, _ = run_check(make_runner(funnel=FUNNEL_FILES))
    assert keys == ["funnel:https://vmi3495713.tailce2ab5.ts.net"]


def test_parse_ssh_accepted_sshd_session():
    line = "2026-11-09T11:00:00+01:00 vmi sshd-session[4]: Accepted publickey for root from 203.0.113.9 port 5001 ssh2"
    assert watch.parse_ssh_accepted(line)[0]["ip"] == "203.0.113.9"
