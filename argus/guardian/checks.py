import os
from dataclasses import dataclass
from enum import Enum

import docker
import httpx

from db import update_state

_APP_CONTAINER = os.environ.get("ARGUS_APP_CONTAINER", "argus-app")
_LIQ_CONTAINER = os.environ.get("ARGUS_LIQ_CONTAINER", "argus-liq-listener")
_HEALTH_URL = os.environ.get("ARGUS_HEALTH_URL", "http://app:8080/health")


class Status(Enum):
    OK = "ok"
    KNOWN_ISSUE = "known_issue"
    UNKNOWN_ANOMALY = "unknown_anomaly"


@dataclass
class CheckResult:
    name: str
    status: Status
    message: str
    remediation: str | None = None
    logs_snippet: str | None = None


def check_container_liveness(state: dict) -> "CheckResult":
    client = docker.from_env()
    for cname in (_APP_CONTAINER, _LIQ_CONTAINER):
        try:
            c = client.containers.get(cname)
        except docker.errors.NotFound:
            return CheckResult(
                name="container_liveness",
                status=Status.KNOWN_ISSUE,
                message=f"⚠️ argus-guardian: container {cname} not found.",
            )
        if c.status != "running":
            c.restart()
            return CheckResult(
                name="container_liveness",
                status=Status.KNOWN_ISSUE,
                message=f"⚠️ argus-guardian: {cname} was {c.status}. Restarted.",
                remediation=f"docker restart {cname}",
            )
    # Health endpoint check
    try:
        r = httpx.get(_HEALTH_URL, timeout=5)
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code}")
        if r.json().get("status") != "ok":
            raise ValueError(f"payload: {r.text[:100]}")
    except Exception as e:
        client.containers.get(_APP_CONTAINER).restart()
        return CheckResult(
            name="container_liveness",
            status=Status.KNOWN_ISSUE,
            message=f"⚠️ argus-guardian: health failed ({e}). Restarted app.",
            remediation=f"docker restart {_APP_CONTAINER}",
        )
    return CheckResult(name="container_liveness", status=Status.OK, message="")
