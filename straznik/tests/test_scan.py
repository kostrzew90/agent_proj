import subprocess
from types import SimpleNamespace

from straznik import scan
from straznik.common import load_state

REPORT = {
    "SchemaVersion": 2,
    "Results": [
        {"Target": "postgres:16-alpine (alpine 3.20)", "Vulnerabilities": [
            {"VulnerabilityID": "CVE-1", "PkgName": "openssl", "InstalledVersion": "3.0.1",
             "FixedVersion": "3.0.2", "Severity": "CRITICAL"},
            {"VulnerabilityID": "CVE-2", "PkgName": "zlib", "InstalledVersion": "1.2",
             "FixedVersion": "", "Severity": "HIGH"},
            {"VulnerabilityID": "CVE-3", "PkgName": "curl", "InstalledVersion": "8.0",
             "FixedVersion": "8.1", "Severity": "MEDIUM"},
            {"VulnerabilityID": "CVE-4", "PkgName": "busybox", "InstalledVersion": "1.0",
             "Severity": "HIGH"},
            {"VulnerabilityID": "CVE-5", "PkgName": "musl", "InstalledVersion": "1.1",
             "FixedVersion": "1.2", "Severity": "HIGH"},
        ]},
        {"Target": "app", "Class": "lang-pkgs"},
    ],
}


def cp(rc=0, out="", err=""):
    return SimpleNamespace(returncode=rc, stdout=out, stderr=err)


def test_parse_trivy_keeps_only_fixable_high_critical():
    got = scan.parse_trivy(REPORT)
    assert got == [
        {"id": "CVE-1", "pkg": "openssl", "severity": "CRITICAL", "installed": "3.0.1", "fixed_version": "3.0.2"},
        {"id": "CVE-5", "pkg": "musl", "severity": "HIGH", "installed": "1.1", "fixed_version": "1.2"},
    ]
    assert scan.parse_trivy({}) == []


def test_weekly_scan_records_error_per_image(tmp_path, monkeypatch):
    monkeypatch.setenv("STRAZNIK_STATE_DIR", str(tmp_path))
    import json

    def runner(cmd, timeout=120):
        if cmd[:2] == ["docker", "ps"]:
            return cp(0, "good:1\nbad:1\ntimeout:1\ngood:1\njunk:1\n")
        image = cmd[-1]
        assert "--memory" in cmd and "1536m" in cmd and "--scanners" in cmd
        assert "PINNED@sha256:abc" in cmd and not any(c.endswith(":latest") for c in cmd)
        if image == "bad:1":
            return cp(1, "", "boom")
        if image == "timeout:1":
            raise subprocess.TimeoutExpired(cmd, timeout)
        if image == "junk:1":
            return cp(0, "not json")
        return cp(0, json.dumps(REPORT))

    res = scan.weekly_scan(runner=runner, config={"trivy_image": "PINNED@sha256:abc"})
    assert set(res["images"]) == {"good:1"}
    assert len(res["images"]["good:1"]) == 2
    assert set(res["errors"]) == {"bad:1", "timeout:1", "junk:1"}
    assert "boom" in res["errors"]["bad:1"]
    assert load_state("trivy")["images"]["good:1"][0]["id"] == "CVE-1"
    assert load_state("trivy")["scanned_at"]


def _cfg():
    return {"categories": {"B": [
        {"container": "litellm", "image": "ghcr.io/berriai/litellm:v1.106.6", "github_repo": "BerriAI/litellm"},
        {"container": "argus-grafana", "image": "grafana/grafana:latest"},
        {"container": "same", "image": "x/same:latest"},
    ]}}


def test_check_versions_newer_release_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("STRAZNIK_STATE_DIR", str(tmp_path))
    urls = []

    def fetch(url):
        urls.append(url)
        return {"tag_name": "v1.107.0"}

    res = scan.check_versions(runner=lambda c, timeout=120: cp(1, "", "x"), fetch=fetch, config=_cfg())
    item = res["results"]["litellm"]
    assert item["newer"] is True and item["current"] == "1.106.6" and item["latest"] == "1.107.0"
    assert urls == ["https://api.github.com/repos/BerriAI/litellm/releases/latest"]
    assert load_state("versions")["results"]["litellm"]["newer"] is True


def test_check_versions_same_release_and_fetch_error(tmp_path, monkeypatch):
    monkeypatch.setenv("STRAZNIK_STATE_DIR", str(tmp_path))
    r = lambda c, timeout=120: cp(1, "", "x")
    res = scan.check_versions(runner=r, fetch=lambda u: {"tag_name": "v1.106.6"}, config=_cfg())
    assert res["results"]["litellm"]["newer"] is False

    def boom(url):
        raise OSError("net")

    res = scan.check_versions(runner=r, fetch=boom, config=_cfg())
    assert "litellm" in res["errors"] and "litellm" not in res["results"]


def test_check_versions_digest_changed_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("STRAZNIK_STATE_DIR", str(tmp_path))

    def runner(cmd, timeout=120):
        if cmd[:3] == ["docker", "buildx", "imagetools"]:
            return cp(0, '"sha256:new"\n') if cmd[4] == "grafana/grafana:latest" else cp(0, '"sha256:same"\n')
        if cmd[:3] == ["docker", "image", "inspect"]:
            return cp(0, '["grafana/grafana@sha256:old"]\n') if cmd[3] == "grafana/grafana:latest" \
                else cp(0, '["x/same@sha256:same"]\n')
        return cp(1)

    res = scan.check_versions(runner=runner, fetch=lambda u: {"tag_name": "v1.106.6"}, config=_cfg())
    assert res["results"]["argus-grafana"]["newer"] is True
    assert res["results"]["argus-grafana"]["kind"] == "digest"
    assert res["results"]["same"]["newer"] is False


def test_weekly_scan_docker_ps_failure_keeps_previous_state():
    from straznik.common import save_state
    save_state("trivy", {"scanned_at": "old", "images": {"a:1": []}, "errors": {}})
    res = scan.weekly_scan(runner=lambda cmd, timeout=120: cp(1, "", "daemon down"))
    assert "docker ps" in res["errors"]
    assert load_state("trivy") == {"scanned_at": "old", "images": {"a:1": []}, "errors": {}}


def test_check_versions_github_without_tag_name_records_error():
    res = scan.check_versions(runner=lambda c, timeout=120: cp(1), fetch=lambda u: {}, config=_cfg())
    assert "litellm" in res["errors"] and "litellm" not in res["results"]
