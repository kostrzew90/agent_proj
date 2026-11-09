import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select, func

from argus.models import FearGreed

logger = logging.getLogger(__name__)

_URL = "https://api.alternative.me/fng/"
_MAX_AGE_DAYS = 2


def fetch_fear_greed(limit: int) -> list[dict]:
    r = httpx.get(_URL, params={"limit": limit}, timeout=20)
    r.raise_for_status()
    rows = []
    for d in r.json()["data"]:
        rows.append({
            "date": datetime.fromtimestamp(int(d["timestamp"]), tz=timezone.utc).date(),
            "value": int(d["value"]),
            "classification": d["value_classification"],
        })
    return rows


def collect_fear_greed(session) -> int:
    empty = session.scalar(select(func.count()).select_from(FearGreed)) == 0
    rows = fetch_fear_greed(0 if empty else 3)
    now = datetime.now(timezone.utc)
    for row in rows:
        session.merge(FearGreed(fetched_at=now, **row))
    session.commit()
    return len(rows)


def get_current_fng(session) -> int | None:
    row = session.scalar(select(FearGreed).order_by(FearGreed.date.desc()).limit(1))
    if row is None:
        return None
    if row.date < datetime.now(timezone.utc).date() - timedelta(days=_MAX_AGE_DAYS):
        return None
    return row.value
