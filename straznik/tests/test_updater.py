import gzip
import json
import os
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from straznik import updater
from straznik.common import load_state, save_state

NOW = datetime(2026, 11, 10, 4, 0, tzinfo=timezone.utc)
OLD = "sha256:old"
NEW = "sha256:new"


def info(name, image="postgres:16-alpine", wd="/root/argus", service="db", status="running",
         health="healthy", restarts=0, img=OLD, env=("POSTGRES_USER=argus",)):
    return {
        "Image": img,
        "RestartCount": restarts,
        "State": {"Status": status, "Health": {"Status": health} if health else None},
        "Config": {"Image": image, "Env": list(env), "Labels": {
            "com.docker.compose.project.working_dir": wd,
            "com.docker.compose.service": service,
            "com.docker.compose.project": "argus"}},
    }


class Fake:
    """Atrapa runnera: inspect z tabeli, reszta wg prefiksu -> (kod, stdout)."""

    def __init__(self, inspects, rules=None):
        self.inspects = inspects
        self.rules = {"docker compose": (0, ""), "docker tag": (0, ""),
                      "docker image inspect": (0, NEW + "\n"),
                      "docker exec": (0, "-- dump\n"), "fuser": (1, "")}
        self.rules.update(rules or {})
        self.calls = []
        self.after_up = None
        self.up_effects = []   # 0 / rc / Exception per kolejne `up -d`
        self.ups = 0
        self.rolled = False
        self.dump_ok = True

    def dumper(self, cmd, tmp):
        self.calls.append(" ".join(cmd))
        if not self.dump_ok:
            with open(tmp, "wb") as f:
                f.write(b"partial")
            return False
        with gzip.open(tmp, "wb") as f:
            f.write(b"-- dump\n")
        return True

    def __call__(self, cmd, timeout=120):
        line = " ".join(cmd)
        self.calls.append(line)
        if cmd[:2] == ["docker", "tag"] and "straznik-rollback" in cmd[2]:
            self.rolled = True
        if cmd[:2] == ["docker", "inspect"]:
            i = self.inspects.get(cmd[2])
            return SimpleNamespace(returncode=0 if i else 1, stdout=json.dumps([i]) if i else "")
        if "up -d" in line:
            effect = self.up_effects[self.ups] if self.ups < len(self.up_effects) else 0
            image = OLD if self.rolled else self.rules["docker image inspect"][1].strip()
            self.ups += 1
            if isinstance(effect, Exception):
                raise effect
            if effect:
                return SimpleNamespace(returncode=effect, stdout="")
            svc = cmd[-1]
            for i in self.inspects.values():
                if i["Config"]["Labels"]["com.docker.compose.service"] == svc:
                    i["Image"] = image
            if self.after_up:
                self.after_up()
        best = max((k for k in self.rules if line.startswith(k)), key=len)
        code, out = self.rules[best]
        return SimpleNamespace(returncode=code, stdout=out)

    def has(self, text):
        return [c for c in self.calls if text in c]


@pytest.fixture
def alerts(monkeypatch):
    sent = []
    monkeypatch.setattr(updater, "alert", lambda key, text, now=None: sent.append((key, text)) or True)
    return sent


ENTRY = {"container": "argus-db-1", "image": "postgres:16-alpine", "postgres": True}
CONFIG = {"categories": {"A": [ENTRY], "B": [{"container": "litellm", "http_check": "http://x/h"}],
                         "C": [{"container": "argus-app", "http_check": "http://app/health"}]}}


def call_update(fake, tmp_path, entry=ENTRY, config=CONFIG, http=lambda u: 200, sleep=lambda s: None, dumper=None):
    return updater.update_one(entry, runner=fake, sleep=sleep, now=NOW, config=config,
                              http_get=http, backup_dir=str(tmp_path / "bk"),
                              dumper=dumper or fake.dumper)


def test_pick_candidates_vulnerable_first_then_oldest():
    cs = [{"container": "a", "image": "x", "image_created": "2026-03"},
          {"container": "b", "image": "y", "image_created": "2026-01"},
          {"container": "c", "image": "z", "image_created": "2026-09"}]
    assert [c["container"] for c in updater.pick_candidates(cs, {"z"})] == ["c", "b", "a"]
    assert [c["container"] for c in updater.pick_candidates(cs, set())] == ["b", "a", "c"]


def test_vulnerable_images():
    t = {"images": {"a": [{"severity": "HIGH", "fixed_version": "1.2"}],
                    "b": [{"severity": "HIGH", "fixed_version": ""}],
                    "c": [{"severity": "LOW", "fixed_version": "1"}]}}
    assert updater.vulnerable_images(t) == {"a"}
    assert updater.vulnerable_images({}) == set()
    assert updater.vulnerable_images("x") == set()


def test_update_unchanged_image_no_restart(tmp_path, alerts):
    fake = Fake({"argus-db-1": info("argus-db-1")}, {"docker image inspect": (0, OLD + "\n")})
    assert call_update(fake, tmp_path) == "unchanged"
    assert not fake.has("up -d") and not fake.has("docker tag")


def test_update_healthy_postgres_dumps_first(tmp_path, alerts):
    fake = Fake({"argus-db-1": info("argus-db-1"), "argus-app": info("argus-app")})
    assert call_update(fake, tmp_path) == "updated"
    order = [next(i for i, c in enumerate(fake.calls) if k in c)
             for k in ("pull db", "docker tag sha256:old postgres:straznik-rollback-argus-db-1",
                       "pg_dumpall -U argus", "up -d")]
    assert order == sorted(order)
    files = list((tmp_path / "bk").glob("argus-db-1-20261110-0400.sql.gz"))
    assert len(files) == 1 and gzip.open(files[0], "rt").read() == "-- dump\n"
    assert not alerts


def test_dump_rotation_keeps_7(tmp_path, alerts):
    bk = tmp_path / "bk"
    bk.mkdir()
    for i in range(9):
        (bk / f"argus-db-1-2026110{i}-0400.sql.gz").write_text("x")
    fake = Fake({"argus-db-1": info("argus-db-1")})
    assert call_update(fake, tmp_path) == "updated"
    assert len(list(bk.glob("argus-db-1-*.sql.gz"))) == 7


def test_update_unhealthy_rolls_back_and_alerts(tmp_path, alerts):
    fake = Fake({"argus-db-1": info("argus-db-1")})

    def after_up():
        fake.inspects["argus-db-1"] = info("argus-db-1", health="unhealthy" if fake.ups == 1 else "healthy",
                                           img=NEW if fake.ups == 1 else OLD)

    fake.after_up = after_up
    assert call_update(fake, tmp_path) == "rolled_back"
    assert len(fake.has("up -d")) == 2
    assert fake.has("docker tag postgres:straznik-rollback-argus-db-1 postgres:16-alpine")
    assert alerts == [("update:argus-db-1",
                       "⚠️ Aktualizacja argus-db-1 nieudana — przywrócono poprzedni obraz.")]
    assert load_state("updates_blocked") == {"argus-db-1": NEW}


def test_rolled_back_image_not_retried(tmp_path, alerts):
    save_state("updates_blocked", {"argus-db-1": NEW})
    fake = Fake({"argus-db-1": info("argus-db-1")})
    assert call_update(fake, tmp_path) == "unchanged"
    assert not fake.has("up -d")
    fake.rules["docker image inspect"] = (0, "sha256:newer\n")
    assert call_update(fake, tmp_path) == "updated"
    assert load_state("updates_blocked") == {}


def test_restart_count_growth_rolls_back(tmp_path, alerts):
    fake = Fake({"argus-db-1": info("argus-db-1")})
    n = {"i": 0}

    def sleep(s):
        n["i"] += 1
        if n["i"] == 2:
            fake.inspects["argus-db-1"] = info("argus-db-1", restarts=1)

    assert call_update(fake, tmp_path, sleep=sleep) == "rolled_back"


def test_update_dependent_http_fail_rolls_back(tmp_path, alerts):
    fake = Fake({"argus-db-1": info("argus-db-1"), "argus-app": info("argus-app", service="app"),
                 "litellm": info("litellm", wd="/root/litellm")})
    seen = []

    def http(url):
        seen.append(url)
        return 502 if "app" in url else 200

    assert call_update(fake, tmp_path, http=http) == "rolled_back"
    assert seen == ["http://app/health"]  # litellm z innego working_dir nie jest sprawdzany
    assert alerts


def test_http_exception_is_unhealthy(tmp_path, alerts):
    fake = Fake({"argus-db-1": info("argus-db-1"), "argus-app": info("argus-app", service="app")})

    def http(url):
        raise OSError("down")

    assert call_update(fake, tmp_path, http=http) == "rolled_back"


def test_dump_failure_aborts_update(tmp_path, alerts):
    fake = Fake({"argus-db-1": info("argus-db-1")}, {})
    fake.dump_ok = False
    assert call_update(fake, tmp_path) == "failed"
    assert not fake.has("up -d")
    assert alerts and alerts[0][0] == "update:argus-db-1"
    assert fake.has("docker tag sha256:old postgres:16-alpine")
    assert not list((tmp_path / "bk").glob("*.tmp"))
    assert not list((tmp_path / "bk").glob("*.sql.gz"))


def test_missing_labels_fails(tmp_path, alerts):
    i = info("argus-db-1")
    i["Config"]["Labels"] = {}
    fake = Fake({"argus-db-1": i})
    assert call_update(fake, tmp_path) == "failed"
    assert not fake.has("pull")


def test_dump_before_uses_other_container(tmp_path, alerts):
    entry = {"container": "langfuse-web", "image": "docker.langfuse.com/langfuse/langfuse:4",
             "dump_before": "langfuse-postgres"}
    fake = Fake({"langfuse-web": info("langfuse-web", image="docker.langfuse.com/langfuse/langfuse:4", health=None, wd="/root/lf", service="web"),
                 "langfuse-postgres": info("langfuse-postgres", env=("POSTGRES_USER=lf",))})
    assert call_update(fake, tmp_path, entry=entry, config={"categories": {"A": [entry]}}) == "updated"
    assert fake.has("docker exec langfuse-postgres pg_dumpall -U lf")
    assert list((tmp_path / "bk").glob("langfuse-web-*.sql.gz"))


# --- nightly ---

def cfg_n(n):
    return {"categories": {"A": [{"container": f"c{i}", "image": f"img{i}:1"} for i in range(n)],
                           "B": [{"container": "bbb", "image": "b:1"}],
                           "C": [{"container": "ccc"}]}}


def fake_n(n, rules=None):
    ins = {f"c{i}": info(f"c{i}", image=f"img{i}:1", service=f"s{i}") for i in range(n)}
    return Fake(ins, rules)


def run_nightly(fake, cfg, tmp_path):
    return updater.nightly(runner=fake, sleep=lambda s: None, now=NOW, config=cfg,
                           http_get=lambda u: 200, backup_dir=str(tmp_path / "bk"), dumper=fake.dumper)


def test_nightly_limit_1_and_3_with_cve(alerts, tmp_path):
    res = run_nightly(fake_n(5), cfg_n(5), tmp_path)
    assert [r["result"] for r in res] == ["updated"]
    save_state("trivy", {"images": {"img3:1": [{"severity": "CRITICAL", "fixed_version": "2"}]}})
    res = run_nightly(fake_n(5), cfg_n(5), tmp_path)
    assert len([r for r in res if r["result"] == "updated"]) == 3
    assert res[0]["container"] == "c3"
    hist = load_state("updates")["items"]
    assert len(hist) == 4 and set(hist[0]) == {"ts", "container", "result", "old_image", "new_image"}


def test_nightly_unchanged_does_not_count(alerts, tmp_path):
    fake = fake_n(3, {"docker image inspect": (0, OLD + "\n")})
    res = run_nightly(fake, cfg_n(3), tmp_path)
    assert [r["result"] for r in res] == ["unchanged"] * 3


def test_nightly_skips_when_apt_busy(alerts, tmp_path):
    fake = fake_n(2, {"fuser": (0, "")})
    res = run_nightly(fake, cfg_n(2), tmp_path)
    assert [r["result"] for r in res] == ["skipped_apt"]
    assert not fake.has("pull")
    assert load_state("updates")["items"][0]["result"] == "skipped_apt"


def test_nightly_missing_or_corrupt_trivy_json_still_runs(alerts, state_dir, tmp_path):
    assert run_nightly(fake_n(2), cfg_n(2), tmp_path)[0]["result"] == "updated"
    (state_dir / "trivy.json").write_text("{not json")
    assert run_nightly(fake_n(2), cfg_n(2), tmp_path)[0]["result"] == "updated"


def test_only_category_A_ever_updated(alerts, tmp_path):
    fake = fake_n(2)
    save_state("trivy", {"images": {"b:1": [{"severity": "HIGH", "fixed_version": "2"}]}})
    run_nightly(fake, cfg_n(2), tmp_path)
    touched = fake.has("pull") + fake.has("up -d")
    assert touched and not any(x in c for c in touched for x in ("bbb", "ccc"))
    assert not any("b:1" in c for c in fake.has("docker tag"))


def test_history_pruned_after_30_days(alerts, tmp_path):
    save_state("updates", {"items": [{"ts": "2026-09-01T00:00:00+00:00", "container": "old"},
                                     {"ts": "2026-11-01T00:00:00+00:00", "container": "recent"}]})
    run_nightly(fake_n(1), cfg_n(1), tmp_path)
    assert [u["container"] for u in load_state("updates")["items"]] == ["recent", "c0"]


# --- ścieżki awarii ---

def test_exception_during_up_rolls_back_and_alerts(tmp_path, alerts):
    fake = Fake({"argus-db-1": info("argus-db-1")})
    fake.up_effects = [TimeoutError("up"), 0]
    assert call_update(fake, tmp_path) == "rolled_back"
    assert len(fake.has("up -d")) == 2
    assert alerts == [("update:argus-db-1",
                       "⚠️ Aktualizacja argus-db-1 nieudana — przywrócono poprzedni obraz.")]


def test_up_nonzero_rc_rolls_back(tmp_path, alerts):
    fake = Fake({"argus-db-1": info("argus-db-1")})
    fake.up_effects = [1, 0]
    assert call_update(fake, tmp_path) == "rolled_back"


def test_forward_up_with_unchanged_image_rolls_back(tmp_path, alerts):
    fake = Fake({"argus-db-1": info("argus-db-1")})
    fake.after_up = lambda: fake.inspects["argus-db-1"].update(Image=OLD) if fake.ups == 1 else None
    assert call_update(fake, tmp_path) == "rolled_back"


def test_failed_rollback_raises_separate_alarm(tmp_path, alerts):
    fake = Fake({"argus-db-1": info("argus-db-1")})
    fake.up_effects = [1, 1]
    assert call_update(fake, tmp_path) == "failed"
    assert alerts == [("rollback:argus-db-1", "🚨 Rollback argus-db-1 NIEUDANY — wymagana interwencja.")]


def test_rollback_exception_is_failed(tmp_path, alerts):
    fake = Fake({"argus-db-1": info("argus-db-1")})
    fake.up_effects = [1, OSError("x")]
    assert call_update(fake, tmp_path) == "failed"
    assert alerts[0][0] == "rollback:argus-db-1"


def test_pull_exception_retags_and_fails(tmp_path, alerts):
    fake = Fake({"argus-db-1": info("argus-db-1")})
    orig = fake.__call__

    class Boom(Fake):
        def __call__(self, cmd, timeout=120):
            if "pull" in cmd:
                raise TimeoutError("pull")
            return Fake.__call__(self, cmd, timeout)

    boom = Boom({"argus-db-1": info("argus-db-1")})
    assert call_update(boom, tmp_path) == "failed"
    assert boom.has("docker tag sha256:old postgres:16-alpine") and not boom.has("up -d")
    assert alerts


def test_tag_failure_retags_old_image(tmp_path, alerts):
    fake = Fake({"argus-db-1": info("argus-db-1")}, {"docker tag": (1, "")})
    assert call_update(fake, tmp_path) == "failed"
    assert not fake.has("up -d")
    assert len(fake.has("docker tag sha256:old postgres:16-alpine")) == 1


def test_nightly_exception_records_failed_and_continues(alerts, tmp_path):
    class Boom(Fake):
        def __call__(self, cmd, timeout=120):
            if cmd[:2] == ["docker", "inspect"] and cmd[2] == "c0":
                raise FileNotFoundError("docker")
            return Fake.__call__(self, cmd, timeout)

    fake = Boom({f"c{i}": info(f"c{i}", image=f"img{i}:1", service=f"s{i}") for i in range(2)})
    res = run_nightly(fake, cfg_n(2), tmp_path)
    assert [r["result"] for r in res] == ["failed", "updated"]
    assert len(load_state("updates")["items"]) == 2
    assert any(k == "update:c0" for k, _ in alerts)


def test_dump_dir_and_file_private(tmp_path, alerts):
    if os.name == "nt":
        pytest.skip("tryby uprawnień POSIX")
    fake = Fake({"argus-db-1": info("argus-db-1")})
    assert call_update(fake, tmp_path) == "updated"
    assert (tmp_path / "bk").stat().st_mode & 0o777 == 0o700
    f = next((tmp_path / "bk").glob("*.sql.gz"))
    assert f.stat().st_mode & 0o777 == 0o600


def test_stream_dump_real_process(tmp_path):
    import sys
    out = tmp_path / "x.gz"
    assert updater._stream_dump([sys.executable, "-c", "print('hi')"], out)
    assert gzip.open(out, "rt").read().strip() == "hi"
    assert not updater._stream_dump([sys.executable, "-c", "import sys;sys.exit(3)"], out)


def test_nightly_stops_after_failed_rollback(alerts, tmp_path):
    save_state("trivy", {"images": {f"img{i}:1": [{"severity": "HIGH", "fixed_version": "2"}] for i in range(3)}})
    fake = fake_n(3)
    fake.up_effects = [1, 1]  # up nieudane, rollback nieudany
    res = run_nightly(fake, cfg_n(3), tmp_path)
    assert [r["result"] for r in res] == ["failed"]
    assert len(fake.has("pull")) == 1
    assert [k for k, _ in alerts] == ["rollback:c0"]
    assert len(load_state("updates")["items"]) == 1


def test_block_state_write_failure_does_not_prevent_rollback(tmp_path, alerts, monkeypatch):
    def boom(name, data):
        if name == "updates_blocked":
            raise OSError("disk full")
        return save_state(name, data)

    monkeypatch.setattr(updater, "save_state", boom)
    fake = Fake({"argus-db-1": info("argus-db-1")})
    fake.up_effects = [1, 0]
    assert call_update(fake, tmp_path) == "rolled_back"
    assert fake.has("docker tag postgres:straznik-rollback-argus-db-1 postgres:16-alpine")
    assert len(fake.has("up -d")) == 2
    assert alerts == [("update:argus-db-1",
                       "⚠️ Aktualizacja argus-db-1 nieudana — przywrócono poprzedni obraz.")]


# --- poprawki z przeglądu końcowego ---

def test_compose_passes_env_files(tmp_path, alerts):
    i = info("argus-db-1")
    i["Config"]["Labels"]["com.docker.compose.project.environment_file"] = "/root/argus/.env,/root/x.env"
    fake = Fake({"argus-db-1": i})
    assert call_update(fake, tmp_path) == "updated"
    pull = fake.has("pull db")[0]
    assert "--env-file /root/argus/.env --env-file /root/x.env pull db" in pull


def test_image_mismatch_aborts_without_pull(tmp_path, alerts):
    fake = Fake({"argus-db-1": info("argus-db-1", image="postgres:17")})
    assert call_update(fake, tmp_path) == "failed"
    assert not fake.has("pull") and not fake.has("up -d")
    assert alerts and alerts[0][0] == "update:argus-db-1"


def test_db_uses_stop_timeout_60_others_not(tmp_path, alerts):
    fake = Fake({"argus-db-1": info("argus-db-1")})
    assert call_update(fake, tmp_path) == "updated"
    assert fake.has("up -d --no-deps -t 60 db")
    entry = {"container": "c0", "image": "img0:1"}
    fake = Fake({"c0": info("c0", image="img0:1", service="s0")})
    assert call_update(fake, tmp_path, entry=entry, config={"categories": {"A": [entry]}}) == "updated"
    assert fake.has("up -d --no-deps s0") and not fake.has("-t 60")
    ch = {"container": "ch", "image": "clickhouse/clickhouse-server:25.12"}
    fake = Fake({"ch": info("ch", image=ch["image"], service="ch")})
    assert call_update(fake, tmp_path, entry=ch, config={"categories": {"A": [ch]}}) == "updated"
    assert fake.has("-t 60 ch")


def test_sibling_without_http_check_restart_triggers_rollback(tmp_path, alerts):
    cfg = {"categories": {"A": [ENTRY], "B": [{"container": "sib"}]}}
    fake = Fake({"argus-db-1": info("argus-db-1"), "sib": info("sib", service="sib")})
    n = {"i": 0}

    def sleep(s):
        n["i"] += 1
        if n["i"] == 14:  # już w fazie pilnowania zależnych (po 12 krokach własnej)
            fake.inspects["sib"]["RestartCount"] = 1

    assert call_update(fake, tmp_path, config=cfg, sleep=sleep) == "rolled_back"


def test_sibling_stopped_before_update_is_ignored(tmp_path, alerts):
    cfg = {"categories": {"A": [ENTRY], "B": [{"container": "sib"}]}}
    fake = Fake({"argus-db-1": info("argus-db-1"), "sib": info("sib", service="sib", status="exited")})
    assert call_update(fake, tmp_path, config=cfg) == "updated"


def test_pull_failure_single_alarm_and_stops_night(alerts, tmp_path):
    fake = fake_n(3, {"docker compose": (1, "")})
    res = run_nightly(fake, cfg_n(3), tmp_path)
    assert [r["result"] for r in res] == ["failed"]
    assert len(fake.has("pull")) == 1
    assert alerts == [("update:pull",
                       "⚠️ Strażnik: pobieranie obrazów nie działa — aktualizacje wstrzymane do jutra.")]


def test_nightly_skips_when_scan_active(alerts, tmp_path):
    fake = fake_n(2, {"systemctl": (0, "active\n")})
    res = run_nightly(fake, cfg_n(2), tmp_path)
    assert [r["result"] for r in res] == ["skipped_scan"]
    assert not fake.has("pull")
    assert fake.has("systemctl is-active straznik-scan.service")


def test_dry_run_changes_nothing_and_reports(tmp_path):
    lines = []
    i = info("argus-db-1")
    i["Config"]["Labels"]["com.docker.compose.project.environment_file"] = "/root/argus/.env"
    cfg_json = json.dumps({"services": {"db": {"pull_policy": "always"}}})

    class DR(Fake):
        def __call__(self, cmd, timeout=120):
            line = " ".join(cmd)
            if "config --format json" in line:
                self.calls.append(line)
                return SimpleNamespace(returncode=0, stdout=cfg_json)
            if "imagetools" in line:
                self.calls.append(line)
                return SimpleNamespace(returncode=0, stdout='"sha256:remote"', stderr="")
            if "{{json .RepoDigests}}" in line:
                self.calls.append(line)
                return SimpleNamespace(returncode=0, stdout='["postgres@sha256:local"]', stderr="")
            return Fake.__call__(self, cmd, timeout)

    fake = DR({"argus-db-1": i})
    updater.dry_run(config={"categories": {"A": [ENTRY]}}, runner=fake, out=lines.append)
    text = "\n".join(lines)
    assert "--env-file /root/argus/.env" in text and "config -q: rc=0" in text
    assert "pull_policy: always = tak" in text and "nowszy obraz w rejestrze: tak" in text
    assert not fake.has(" pull") and not fake.has("up -d") and not fake.has("docker tag")


def test_main_dry_run_flag(monkeypatch):
    called = []
    monkeypatch.setattr(updater, "dry_run", lambda: called.append("dry"))
    monkeypatch.setattr(updater, "nightly", lambda: called.append("night"))
    updater.main(["--dry-run"])
    updater.main([])
    assert called == ["dry", "night"]
