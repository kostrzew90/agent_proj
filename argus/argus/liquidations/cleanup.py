from datetime import datetime, timedelta, timezone
from sqlalchemy import delete
from argus.models import Liquidation


def prune_liquidations(session, days: int = 30) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    res = session.execute(delete(Liquidation).where(Liquidation.ts < cutoff))
    session.commit()
    return res.rowcount or 0
