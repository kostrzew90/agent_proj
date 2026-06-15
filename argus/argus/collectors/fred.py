"""FRED macro data collector — Federal Reserve Economic Data."""
import logging
import os
from datetime import date, datetime, timezone

import httpx
from sqlalchemy import select, text

from argus.models import MacroData

logger = logging.getLogger(__name__)

_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Key series: id → human label
SERIES: dict[str, str] = {
    "DFF":      "Fed Funds Rate (daily)",
    "T10Y2Y":   "10Y-2Y Yield Spread",
    "M2SL":     "M2 Money Supply (bn USD)",
    "CPIAUCSL": "CPI All Urban (index)",
    "DTWEXBGS": "USD Broad Dollar Index",
}


def fetch_series(series_id: str, api_key: str, lookback: int = 12) -> list[dict]:
    """Fetch last `lookback` observations from FRED. Returns parsed rows (no '.' values)."""
    r = httpx.get(
        _BASE,
        params={
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": lookback,
        },
        timeout=30,
    )
    r.raise_for_status()
    return parse_observations(series_id, r.json())


def parse_observations(series_id: str, data: dict) -> list[dict]:
    """Parse FRED JSON response into list of {series_id, date, value} dicts."""
    rows = []
    for obs in data.get("observations", []):
        val_str = obs.get("value", ".")
        if val_str == ".":
            continue
        try:
            rows.append({
                "series_id": series_id,
                "date": datetime.strptime(obs["date"], "%Y-%m-%d").date(),
                "value": float(val_str),
            })
        except Exception as e:
            logger.debug("fred parse error %s %s: %s", series_id, obs, e)
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


def collect_fred(session, api_key: str, lookback: int = 12) -> dict:
    stats = {"inserted": 0, "skipped": 0, "errors": 0}
    for series_id in SERIES:
        try:
            rows = fetch_series(series_id, api_key, lookback)
        except Exception as e:
            logger.warning("fred fetch failed %s: %s", series_id, e)
            stats["errors"] += 1
            continue
        for row in rows:
            existing = session.scalar(
                select(MacroData).where(
                    MacroData.series_id == row["series_id"],
                    MacroData.obs_date == row["date"],
                )
            )
            if existing is not None:
                stats["skipped"] += 1
                continue
            session.add(MacroData(
                series_id=row["series_id"],
                obs_date=row["date"],
                value=row["value"],
                fetched_at=datetime.now(timezone.utc),
            ))
            stats["inserted"] += 1
    session.commit()
    logger.info("fred collect: %s", stats)
    return stats


def get_latest_macro(session) -> dict:
    """Return latest value per series as {series_id: {value, date, label}}."""
    rows = session.execute(
        text("""
            SELECT DISTINCT ON (series_id)
                series_id, obs_date, value
            FROM macro_data
            ORDER BY series_id, obs_date DESC
        """)
    ).fetchall()
    return {
        r.series_id: {
            "value": r.value,
            "date": r.obs_date.isoformat(),
            "label": SERIES.get(r.series_id, r.series_id),
        }
        for r in rows
    }
