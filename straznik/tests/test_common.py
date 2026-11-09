from datetime import datetime, timedelta, timezone

from straznik import common


def test_state_roundtrip_and_corrupt(state_dir):
    common.save_state("x", {"a": 1, "b": "zażółć"})
    assert common.load_state("x") == {"a": 1, "b": "zażółć"}
    (state_dir / "x.json").write_text("{nie json")
    assert common.load_state("x") == {}
    assert common.load_state("brak") == {}


def test_read_env_value_quotes(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# komentarz\nA=1\nB=\"dwa\"\nC='trzy'\nD = x\n")
    assert common.read_env_value(str(f), "A") == "1"
    assert common.read_env_value(str(f), "B") == "dwa"
    assert common.read_env_value(str(f), "C") == "trzy"
    assert common.read_env_value(str(f), "D") == "x"
    assert common.read_env_value(str(f), "Z") is None
    assert common.read_env_value(str(tmp_path / "nie-ma"), "A") is None


def test_alert_dedup_6h():
    t0 = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
    sent = []

    def s(text):
        sent.append(text)
        return True

    assert common.alert("k", "a", now=t0, sender=s) is True
    assert common.alert("k", "a", now=t0 + timedelta(hours=5, minutes=59), sender=s) is False
    assert common.alert("k", "a", now=t0 + timedelta(hours=6, minutes=1), sender=s) is True
    assert common.alert("inny", "b", now=t0, sender=s) is True
    assert len(sent) == 3


def test_alert_not_marked_when_send_fails():
    t0 = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
    calls = []

    def bad(text):
        calls.append(1)
        return False

    assert common.alert("k", "a", now=t0, sender=bad) is False
    assert common.alert("k", "a", now=t0 + timedelta(minutes=5), sender=bad) is False
    assert len(calls) == 2


def test_send_telegram_without_token_returns_false(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "ARGUS_ENV", str(tmp_path / "brak"))
    assert common.send_telegram("x") is False


def test_config_has_all_categories():
    cfg = common.load_config()
    cats = {k: [e["container"] for e in v] for k, v in cfg["categories"].items()}
    assert all(cats[k] for k in "ABC")
    assert "argus-db-1" in cats["A"]
    assert "litellm" in cats["B"]
    assert "argus-grafana" in cats["B"]
    assert "argus-app" in cats["C"]
    entries = {e["container"]: e for v in cfg["categories"].values() for e in v}
    assert "langfuse-web" in cats["B"] and "langfuse-worker" in cats["B"]
    assert "langfuse-web" not in cats["A"] and "langfuse-worker" not in cats["A"]
    assert not any("dump_before" in e for e in entries.values())
    assert "@sha256:" in cfg["trivy_image"] and "latest" not in cfg["trivy_image"]
    assert {"fd7a:115c:a1e0::/48", "::1/128"} <= set(cfg["crowdsec_whitelist"])
    assert entries["korczaka-grav"]["http_check"] == "http://127.0.0.1:8096/"
    assert len(entries) == 34
    assert cfg["allowed_public_ports"] == ["22/tcp", "8096/tcp", "41641/udp"]


def test_whitelist_and_install_cover_ipv6():
    from pathlib import Path
    import yaml
    deploy = Path(__file__).resolve().parent.parent / "deploy"
    wl = yaml.safe_load((deploy / "crowdsec" / "whitelist-straznik.yaml").read_text(encoding="utf-8"))
    assert {"fd7a:115c:a1e0::/48", "::1/128"} <= set(wl["whitelist"]["cidr"])
    assert set(common.load_config()["crowdsec_whitelist"]) == set(wl["whitelist"]["cidr"])
    sh = (deploy / "install.sh").read_text(encoding="utf-8")
    assert sh.count("fd7a:115c:a1e0::/48 ::1/128") == 2
    assert "straznik-update.timer" not in sh.split("systemctl enable --now")[1].splitlines()[0]
    assert "cscli collections list -o json" in sh and "ip6tables -S DOCKER-USER" in sh


def test_update_and_scan_timers_not_persistent():
    from pathlib import Path
    d = Path(__file__).resolve().parent.parent / "deploy" / "systemd"
    for t in ("update", "scan"):
        assert "Persistent=false" in (d / f"straznik-{t}.timer").read_text(encoding="utf-8")
    assert "Persistent=true" in (d / "straznik-report.timer").read_text(encoding="utf-8")
