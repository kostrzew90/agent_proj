import math
from datetime import datetime, timezone
from collections import defaultdict
from sqlalchemy import select
from argus.models import Claim, SourceAssetScore, SourceScore

def trend_lean(session, horizon: str, *, tau_days: float = 7) -> list[dict]:
    now = datetime.now(timezone.utc)
    sas = {(s.source_id, s.asset): s.decayed_score
           for s in session.scalars(select(SourceAssetScore).where(SourceAssetScore.horizon == horizon))}
    src = {s.source_id: s.decayed_score
           for s in session.scalars(select(SourceScore).where(SourceScore.horizon == horizon))}
    agg = defaultdict(float)
    for c in session.scalars(select(Claim).where(Claim.status == "open")):
        score = sas.get((c.source_id, c.asset), src.get(c.source_id, 0.5))
        ets = c.entry_ts if c.entry_ts.tzinfo else c.entry_ts.replace(tzinfo=timezone.utc)
        freshness = math.exp(-((now - ets).total_seconds() / 86400.0) / tau_days)
        sign = {"bull": 1, "bear": -1, "neutral": 0}[c.direction]
        agg[c.asset] += sign * score * c.confidence * freshness
    return [{"asset": a, "lean": round(v, 4)} for a, v in sorted(agg.items())]
