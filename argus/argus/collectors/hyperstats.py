import logging
from datetime import datetime, timezone, timedelta

import httpx
from sqlalchemy import select

from argus.models import Source

logger = logging.getLogger(__name__)
_URL = "https://v2-api.hyperstats.org/api/traders"

def fetch_leaderboard(limit: int = 100) -> list[dict]:
    r = httpx.get(_URL, params={"limit": limit}, timeout=30)
    r.raise_for_status()
    return r.json().get("traders", [])

def _passes_filter(t: dict, min_win_rate: float, min_trades: int, max_age_days: int, now: datetime) -> bool:
    try:
        if float(t.get("winRate", 0) or 0) < min_win_rate:
            return False
        if int(t.get("totalTrades", 0) or 0) < min_trades:
            return False
        la = t.get("lastActivityAt")
        if not la:
            return False
        dt = datetime.fromisoformat(str(la).replace("Z", "+00:00"))
        if dt < now - timedelta(days=max_age_days):
            return False
        grade = (t.get("grade") or "").upper()
        if float(t.get("totalPnl", 0) or 0) <= 0 and not grade.startswith(("A", "S")):
            return False
        return True
    except Exception:
        return False

def sync_top_traders(session, top_n: int = 20, min_win_rate: float = 0.5,
                     min_trades: int = 50, max_age_days: int = 14) -> dict:
    now = datetime.now(timezone.utc)
    stats = {"fetched": 0, "passed_filter": 0, "added": 0,
             "skipped_existing": 0, "skipped_inactive": 0, "errors": 0}
    try:
        traders = fetch_leaderboard(limit=max(top_n * 3, 100))
    except Exception as e:
        logger.warning("hyperstats fetch failed: %s", e)
        stats["errors"] += 1
        return stats
    stats["fetched"] = len(traders)
    passed = [t for t in traders if _passes_filter(t, min_win_rate, min_trades, max_age_days, now)]
    stats["passed_filter"] = len(passed)
    for t in passed[:top_n]:
        addr = (t.get("address") or "").lower()
        if not addr.startswith("0x"):
            continue
        existing = session.scalar(select(Source).where(Source.handle == addr))
        if existing is not None:
            if existing.active:
                stats["skipped_existing"] += 1
            else:
                logger.info("hyperstats: %s tracked but manually deactivated — skipping", addr)
                stats["skipped_inactive"] += 1
            continue
        grade = t.get("grade") or "?"
        session.add(Source(kind="hyperliquid", handle=addr,
                           display_name=f"HL {grade} {addr[:8]}", active=True))
        stats["added"] += 1
    session.commit()
    logger.info("hyperstats sync: %s", stats)
    return stats
