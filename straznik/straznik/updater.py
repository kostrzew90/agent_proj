"""Nocna aktualizacja kontenerów kategorii A: kopia bazy, pull, restart, kontrola zdrowia, rollback."""
import argparse
import gzip
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from straznik.common import alert, load_config, load_state, run, save_state
from straznik.scan import _digest_check

BACKUP_DIR = "/root/backups/straznik"
BACKUP_KEEP = 7
DUMP_TIMEOUT = 1800
HEALTH_WAIT = 120
HEALTH_STEP = 5
RESTART_WATCH = 60
UPDATES_KEEP = timedelta(days=30)
SEVERE = {"CRITICAL", "HIGH"}
STOP_TIMEOUT_DB = "60"


def vulnerable_images(trivy):
    out = set()
    images = trivy.get("images") if isinstance(trivy, dict) else None
    if not isinstance(images, dict):
        return out
    for ref, vulns in images.items():
        if not isinstance(vulns, list):
            continue
        for v in vulns:
            if isinstance(v, dict) and v.get("severity") in SEVERE and v.get("fixed_version"):
                out.add(ref)
                break
    return out


def pick_candidates(containers, vulnerable):
    return sorted(
        containers,
        key=lambda e: (0 if e.get("image") in vulnerable else 1, e.get("image_created") or ""),
    )


def apt_busy(runner=run):
    try:
        return runner(["fuser", "/var/lib/dpkg/lock-frontend"]).returncode == 0
    except Exception:
        return False


def _http_get(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def _http_ok(url, http_get):
    try:
        return http_get(url) < 500
    except Exception:
        return False


def _inspect(name, runner):
    try:
        r = runner(["docker", "inspect", name])
        if r.returncode != 0:
            return None
        data = json.loads(r.stdout)
        return data[0] if isinstance(data, list) and data else None
    except Exception:
        return None


def _repo(ref):
    head, sep, tail = ref.rpartition(":")
    return head if sep and "/" not in tail else ref


def _compose(info, *args):
    labels = (info.get("Config") or {}).get("Labels") or {}
    cmd = ["docker", "compose", "--project-directory", labels["com.docker.compose.project.working_dir"]]
    project = labels.get("com.docker.compose.project")
    if project:
        cmd += ["-p", project]
    files = labels.get("com.docker.compose.project.config_files")
    if files:
        for f in files.split(","):
            cmd += ["-f", f]
    env_files = labels.get("com.docker.compose.project.environment_file")
    if env_files:
        for f in env_files.split(","):
            if f:
                cmd += ["--env-file", f]
    return cmd + list(args)


def _is_db(entry):
    return bool(entry.get("postgres")) or "clickhouse" in (entry.get("image") or "")


def _up_args(entry, service):
    args = ["up", "-d", "--no-deps"]
    if _is_db(entry):
        args += ["-t", STOP_TIMEOUT_DB]  # bazy dostają 60 s na czyste zatrzymanie zamiast domyślnych 10 s
    return args + [service]


def _env_value(info, key, default):
    for item in (info.get("Config") or {}).get("Env") or []:
        if item.startswith(key + "="):
            return item.split("=", 1)[1]
    return default


def _stream_dump(cmd, tmp):
    """Strumieniuje wynik polecenia do gzip; True gdy kod wyjścia 0."""
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
        timer = threading.Timer(DUMP_TIMEOUT, proc.kill)
        timer.start()
        try:
            with gzip.open(tmp, "wb") as f:
                shutil.copyfileobj(proc.stdout, f)
            return proc.wait() == 0
        finally:
            timer.cancel()
            proc.kill()


def _dump(target, owner, runner, now, backup_dir, dumper=_stream_dump):
    """Zrzut pg_dumpall do <owner>-<czas>.sql.gz (katalog 0700, plik 0600); True przy sukcesie."""
    info = _inspect(target, runner)
    if info is None:
        return False
    user = _env_value(info, "POSTGRES_USER", "postgres")
    d = Path(backup_dir)
    path = d / f"{owner}-{now.strftime('%Y%m%d-%H%M')}.sql.gz"
    tmp = d / (path.name + ".tmp")
    try:
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(d, 0o700)
        os.close(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600))
        if not dumper(["docker", "exec", target, "pg_dumpall", "-U", user], tmp):
            raise OSError("pg_dumpall nieudany")
        os.chmod(tmp, 0o600)
        tmp.replace(path)
        for old in sorted(d.glob(f"{owner}-*.sql.gz"))[:-BACKUP_KEEP]:
            old.unlink()
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
    return True


def _healthy(name, runner, sleep):
    """Czeka do 120 s na running+healthy, potem 60 s pilnuje RestartCount."""
    waited = 0
    restarts = None
    while True:
        info = _inspect(name, runner)
        state = (info or {}).get("State") or {}
        health = state.get("Health")
        if state.get("Status") == "running" and (health is None or health.get("Status") == "healthy"):
            restarts = info.get("RestartCount", 0)
            break
        if waited >= HEALTH_WAIT:
            return False
        sleep(HEALTH_STEP)
        waited += HEALTH_STEP
    watched = 0
    while watched < RESTART_WATCH:
        sleep(HEALTH_STEP)
        watched += HEALTH_STEP
        info = _inspect(name, runner)
        state = (info or {}).get("State") or {}
        if state.get("Status") != "running":
            return False
        if info.get("RestartCount", 0) > restarts:
            return False
    return True


def _dependents(name, entry, working_dir, config, runner):
    """[(kontener|None, RestartCount, http_check)] dla kontenerów z tego samego working_dir; własny http_check osobno."""
    out = []
    if entry.get("http_check"):
        out.append((None, 0, entry["http_check"]))
    for entries in (config.get("categories") or {}).values():
        for other in entries or []:
            if other.get("container") == name:
                continue
            oi = _inspect(other["container"], runner)
            labels = ((oi or {}).get("Config") or {}).get("Labels") or {}
            if labels.get("com.docker.compose.project.working_dir") != working_dir:
                continue
            running = (oi.get("State") or {}).get("Status") == "running"
            out.append((other["container"] if running else None, oi.get("RestartCount", 0),
                        other.get("http_check")))
    return out


def _watch_dependents(deps, runner, sleep):
    """60 s: żaden zależny kontener nie może przestać działać ani się zrestartować."""
    watched = [(n, r) for n, r, _ in deps if n]
    if not watched:
        return True
    for _ in range(0, RESTART_WATCH, HEALTH_STEP):
        sleep(HEALTH_STEP)
        for n, base in watched:
            info = _inspect(n, runner)
            if (((info or {}).get("State") or {}).get("Status") != "running"
                    or info.get("RestartCount", 0) > base):
                return False
    return True


def _running_image(name, runner):
    return (_inspect(name, runner) or {}).get("Image")


def _update(entry, runner, sleep, now, config, http_get, backup_dir, dumper=_stream_dump):
    """Zwraca (wynik, stary_id, nowy_id)."""
    name = entry["container"]
    now = now or datetime.now(timezone.utc)
    info = _inspect(name, runner)
    labels = ((info or {}).get("Config") or {}).get("Labels") or {}
    wd = labels.get("com.docker.compose.project.working_dir")
    service = labels.get("com.docker.compose.service")
    if not info or not wd or not service:
        alert(f"update:{name}", f"⚠️ Aktualizacja {name} pominięta — brak etykiet docker compose.", now=now)
        return "failed", None, None
    old_id = info.get("Image")
    running_ref = (info.get("Config") or {}).get("Image")
    ref = entry.get("image") or running_ref
    if ref != running_ref:
        alert(f"update:{name}",
              f"⚠️ Aktualizacja {name} przerwana — obraz w compose ({running_ref}) różni się od containers.yaml ({ref}).",
              now=now)
        return "failed", old_id, None
    rollback = f"{_repo(ref)}:straznik-rollback-{name}"

    def restore_tag():
        # po pull tag wskazuje nowy obraz; bez odtworzenia późniejszy `compose up` uruchomiłby go bez kopii
        try:
            runner(["docker", "tag", old_id, ref])
        except Exception:
            pass

    def abort(reason, new=None):
        restore_tag()
        alert(f"update:{name}", f"⚠️ Aktualizacja {name} {reason}", now=now)
        return "failed", old_id, new

    def pull_failed():
        restore_tag()
        alert("update:pull", "⚠️ Strażnik: pobieranie obrazów nie działa — aktualizacje wstrzymane do jutra.", now=now)
        return "pull_failed", old_id, None

    new_id = None
    try:
        try:
            r = runner(_compose(info, "pull", service), timeout=900)
        except Exception:
            return pull_failed()
        if r.returncode != 0:
            return pull_failed()
        r = runner(["docker", "image", "inspect", ref, "--format", "{{.Id}}"])
        new_id = r.stdout.strip() if r.returncode == 0 else ""
        if not new_id:
            return abort("nieudana — nie odczytano ID nowego obrazu.")
        if new_id == old_id:
            return "unchanged", old_id, new_id
        blocked = load_state("updates_blocked")
        if blocked.get(name) == new_id:
            restore_tag()
            return "unchanged", old_id, new_id
        if name in blocked:
            del blocked[name]
            save_state("updates_blocked", blocked)

        r = runner(["docker", "tag", old_id, rollback])
        if r.returncode != 0:
            return abort("nieudana — nie utworzono punktu przywracania.", new_id)

        dump_target = name if entry.get("postgres") else entry.get("dump_before")
        if dump_target and not _dump(dump_target, name, runner, now, backup_dir, dumper):
            return abort(f"przerwana — zrzut bazy {dump_target} nieudany.", new_id)
    except Exception as e:
        return abort(f"przerwana — błąd: {type(e).__name__}.", new_id)

    ok = False
    try:
        deps = _dependents(name, entry, wd, config, runner)
        r = runner(_compose(info, *_up_args(entry, service)), timeout=600)
        if r.returncode == 0 and _running_image(name, runner) == new_id and _healthy(name, runner, sleep):
            ok = _watch_dependents(deps, runner, sleep)
            for _, _, url in deps:
                if ok and url and not _http_ok(url, http_get):
                    ok = False
    except Exception:
        ok = False
    if ok:
        return "updated", old_id, new_id

    restored = False
    try:
        r1 = runner(["docker", "tag", rollback, ref])
        r2 = runner(_compose(info, *_up_args(entry, service)), timeout=600)
        restored = (r1.returncode == 0 and r2.returncode == 0 and _running_image(name, runner) == old_id
                    and _healthy(name, runner, sleep))
    except Exception:
        restored = False
    try:
        blocked = load_state("updates_blocked")
        blocked[name] = new_id
        save_state("updates_blocked", blocked)
    except Exception:
        pass  # brak zapisu blokady nie może zasłonić wyniku rollbacku
    if restored:
        alert(f"update:{name}", f"⚠️ Aktualizacja {name} nieudana — przywrócono poprzedni obraz.", now=now)
        return "rolled_back", old_id, new_id
    alert(f"rollback:{name}", f"🚨 Rollback {name} NIEUDANY — wymagana interwencja.", now=now)
    return "rollback_failed", old_id, new_id


def update_one(entry, runner=run, sleep=time.sleep, now=None, config=None, http_get=_http_get,
               backup_dir=BACKUP_DIR, dumper=_stream_dump):
    config = config if config is not None else load_config()
    result = _update(entry, runner, sleep, now, config, http_get, backup_dir, dumper)[0]
    return "failed" if result in ("rollback_failed", "pull_failed") else result


def _scan_active(runner):
    try:
        return runner(["systemctl", "is-active", "straznik-scan.service"]).stdout.strip() == "active"
    except Exception:
        return False


def _image_created(ref, runner):
    try:
        r = runner(["docker", "image", "inspect", ref, "--format", "{{.Created}}"])
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def nightly(runner=run, sleep=time.sleep, now=None, config=None, http_get=_http_get,
            backup_dir=BACKUP_DIR, dumper=_stream_dump):
    now = now or datetime.now(timezone.utc)
    config = config if config is not None else load_config()
    entries = (config.get("categories") or {}).get("A") or []
    results = []

    def record(container, result, old=None, new=None):
        results.append({"ts": now.isoformat(), "container": container, "result": result,
                        "old_image": old, "new_image": new})

    if apt_busy(runner):
        record("-", "skipped_apt")
    elif _scan_active(runner):
        record("-", "skipped_scan")
    else:
        vulnerable = vulnerable_images(load_state("trivy"))
        limit = 3 if vulnerable & {e.get("image") for e in entries} else 1
        enriched = [dict(e, image_created=_image_created(e.get("image"), runner)) for e in entries]
        done = 0
        for entry in pick_candidates(enriched, vulnerable):
            if done >= limit:
                break
            try:
                result, old, new = _update(entry, runner, sleep, now, config, http_get, backup_dir, dumper)
            except Exception as e:
                result, old, new = "failed", None, None
                alert(f"update:{entry['container']}",
                      f"⚠️ Aktualizacja {entry['container']} nieudana — błąd: {type(e).__name__}.", now=now)
            record(entry["container"], "failed" if result in ("rollback_failed", "pull_failed") else result, old, new)
            if result == "pull_failed":
                break  # rejestr/sieć nie działa - alarm update:pull już poszedł, reszta nocy wstrzymana
            if result == "rollback_failed":
                break  # coś jest zepsute na hoście - nie ruszamy kolejnych kontenerów
            if result in ("updated", "rolled_back"):
                done += 1

    history = []
    for u in load_state("updates").get("items", []):
        try:
            if now - datetime.fromisoformat(u["ts"]) <= UPDATES_KEEP:
                history.append(u)
        except (KeyError, ValueError, TypeError):
            continue
    save_state("updates", {"items": history + results})
    return results


def dry_run(config=None, runner=run, out=print):
    """Nic nie pobiera ani nie restartuje; dla każdego kontenera kategorii A pokazuje, co zrobiłaby aktualizacja."""
    config = config if config is not None else load_config()
    for entry in (config.get("categories") or {}).get("A") or []:
        name = entry["container"]
        info = _inspect(name, runner)
        labels = ((info or {}).get("Config") or {}).get("Labels") or {}
        if (not info or not labels.get("com.docker.compose.project.working_dir")
                or not labels.get("com.docker.compose.service")):
            out(f"{name}: brak etykiet docker compose")
            continue
        service = labels["com.docker.compose.service"]
        base = _compose(info)
        out(f"{name}: {' '.join(base)} <polecenie> {service}")
        running_ref = (info.get("Config") or {}).get("Image")
        ref = entry.get("image") or running_ref
        if ref != running_ref:
            out(f"  UWAGA: obraz w compose {running_ref} != containers.yaml {ref} - aktualizacja zostanie przerwana")
        try:
            rc = runner(base + ["config", "-q"]).returncode
        except Exception as e:
            rc = type(e).__name__
        out(f"  compose config -q: rc={rc}")
        try:
            r = runner(base + ["config", "--format", "json"])
            svc = ((json.loads(r.stdout).get("services") or {}).get(service) or {}) if r.returncode == 0 else {}
            out(f"  pull_policy: always = {'tak' if svc.get('pull_policy') == 'always' else 'nie'}")
        except Exception as e:
            out(f"  pull_policy: błąd ({type(e).__name__})")
        try:
            item = _digest_check(ref, runner)
            out(f"  nowszy obraz w rejestrze: {'tak' if item['newer'] else 'nie'}")
        except Exception as e:
            out(f"  nowszy obraz w rejestrze: błąd ({type(e).__name__}: {str(e)[:100]})")
        out(f"  zatrzymanie: {'z -t ' + STOP_TIMEOUT_DB if _is_db(entry) else 'domyślne'}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="straznik.updater")
    ap.add_argument("--dry-run", action="store_true", help="tylko pokaż plan, nic nie pobieraj ani nie restartuj")
    args = ap.parse_args(argv)
    if args.dry_run:
        dry_run()
    else:
        nightly()


if __name__ == "__main__":
    main()
