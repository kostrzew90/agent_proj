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
