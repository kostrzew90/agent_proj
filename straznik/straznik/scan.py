"""Tygodniowy skan Trivy (B, C) i sprawdzanie nowych wersji obrazów kategorii B."""
import json
import subprocess
import urllib.request
from datetime import datetime, timezone

from straznik.common import load_config, run, save_state

SEVERE = {"CRITICAL", "HIGH"}
SCAN_TIMEOUT = 900


def trivy_cmd(config):
    return [
        "docker", "run", "--rm", "--memory", "1536m",
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        "-v", "straznik-trivy-cache:/root/.cache",
        config["trivy_image"], "image", "--scanners", "vuln", "-q", "-f", "json",
    ]


def parse_trivy(report):
    out = []
    for res in (report or {}).get("Results") or []:
        for v in res.get("Vulnerabilities") or []:
            if v.get("Severity") in SEVERE and v.get("FixedVersion"):
                out.append({
                    "id": v.get("VulnerabilityID"),
                    "pkg": v.get("PkgName"),
                    "severity": v["Severity"],
                    "installed": v.get("InstalledVersion"),
                    "fixed_version": v["FixedVersion"],
                })
    return out


def _running_images(runner):
    r = runner(["docker", "ps", "--format", "{{.Image}}"])
    if r.returncode != 0:
        raise RuntimeError(f"docker ps: {(r.stderr or '').strip()[:200]}")
    seen = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if line and line not in seen:
            seen.append(line)
    return seen


def weekly_scan(runner=run, now=None, config=None):
    now = now or datetime.now(timezone.utc)
    cmd = trivy_cmd(config if config is not None else load_config())
    result = {"scanned_at": now.isoformat(), "images": {}, "errors": {}}
    try:
        images = _running_images(runner)
    except Exception as e:
        # nie nadpisujemy poprzedniego trivy.json pustym wynikiem
        result["errors"]["docker ps"] = str(e)[:200]
        return result
    for image in images:
        try:
            r = runner(cmd + [image], timeout=SCAN_TIMEOUT)
            if r.returncode != 0:
                result["errors"][image] = f"trivy rc={r.returncode}: {(r.stderr or '').strip()[-200:]}"
                continue
            result["images"][image] = parse_trivy(json.loads(r.stdout))
        except subprocess.TimeoutExpired:
            result["errors"][image] = f"przekroczono limit {SCAN_TIMEOUT} s"
        except Exception as e:
            result["errors"][image] = f"{type(e).__name__}: {e}"[:200]
    save_state("trivy", result)
    return result


def urlopen_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "straznik"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def latest_github_release(repo, fetch=urlopen_json):
    try:
        tag = fetch(f"https://api.github.com/repos/{repo}/releases/latest").get("tag_name")
        return tag or None
    except Exception:
        return None


def _strip_v(tag):
    return tag[1:] if tag.startswith("v") else tag


def _image_tag(image):
    tail = image.rsplit("/", 1)[-1]
    return tail.split(":", 1)[1] if ":" in tail else "latest"


def _digest_check(image, runner):
    r = runner(["docker", "buildx", "imagetools", "inspect", image, "--format", "{{json .Manifest.Digest}}"])
    if r.returncode != 0:
        raise RuntimeError(f"imagetools: {(r.stderr or '').strip()[:200]}")
    remote = json.loads(r.stdout.strip())
    r = runner(["docker", "image", "inspect", image, "--format", "{{json .RepoDigests}}"])
    if r.returncode != 0:
        raise RuntimeError(f"image inspect: {(r.stderr or '').strip()[:200]}")
    local = [d.split("@", 1)[-1] for d in (json.loads(r.stdout.strip()) or [])]
    return {"kind": "digest", "current": local[0] if local else None, "latest": remote,
            "newer": bool(local) and remote not in local}


def check_versions(runner=run, fetch=urlopen_json, config=None):
    config = config or load_config()
    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "results": {}, "errors": {}}
    for entry in (config.get("categories") or {}).get("B") or []:
        name, image = entry["container"], entry.get("image")
        try:
            if entry.get("github_repo"):
                latest = latest_github_release(entry["github_repo"], fetch)
                if not latest:
                    raise RuntimeError("nie udało się ustalić najnowszego wydania z GitHuba")
                current = _strip_v(_image_tag(image))
                latest = _strip_v(latest)
                item = {"kind": "release", "current": current, "latest": latest, "newer": latest != current}
            else:
                item = _digest_check(image, runner)
            item["image"] = image
            result["results"][name] = item
        except Exception as e:
            result["errors"][name] = f"{type(e).__name__}: {e}"[:200]
    save_state("versions", result)
    return result


def main():
    weekly_scan()
    check_versions()


if __name__ == "__main__":
    main()
