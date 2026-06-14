import math
from datetime import datetime, timezone
from collections import defaultdict
from sqlalchemy import select, delete
from argus.models import Claim, Outcome, SourceAssetScore, SourceScore

_GRADE_THRESHOLDS = [
    (0.70, "S"),
    (0.60, "A"),
    (0.52, "B"),
    (0.45, "C"),
    (0.00, "D"),
]

def argus_grade(decayed_score: float, n_claims: int, min_claims: int = 5) -> str:
    """Letter grade from Argus's own outcome data. '?' until min_claims reached."""
    if n_claims < min_claims:
        return "?"
    for threshold, letter in _GRADE_THRESHOLDS:
        if decayed_score >= threshold:
            return letter
    return "D"

def _age_days(now: datetime, entry_ts: datetime) -> float:
    ets = entry_ts if entry_ts.tzinfo else entry_ts.replace(tzinfo=timezone.utc)
    return (now - ets).total_seconds() / 86400.0

def recompute_scores(session, *, tau_days: float = 14, alpha: float = 2,
                     beta: float = 2, k_min: int = 5) -> None:
    now = datetime.now(timezone.utc)
    claims = {c.id: c for c in session.scalars(select(Claim))}
    groups = defaultdict(list)   # (source_id, asset, horizon) -> [(hit, ret, age_days)]
    for o in session.scalars(select(Outcome)):
        c = claims.get(o.claim_id)
        if c is None:
            continue
        age = _age_days(now, c.entry_ts)
        groups[(c.source_id, c.asset, o.horizon)].append((o.hit, o.return_pct, age))

    session.execute(delete(SourceAssetScore))
    session.execute(delete(SourceScore))

    roll = defaultdict(lambda: {"n": 0, "hits": 0, "ret_sum": 0.0,
                                "w_sum": 0.0, "wh_sum": 0.0})

    for (sid, asset, horizon), rows in groups.items():
        n = len(rows)
        hits = sum(1 for hit, _, _ in rows if hit)
        ret_sum = sum(r for _, r, _ in rows)
        w_sum = sum(math.exp(-age / tau_days) for _, _, age in rows)
        wh_sum = sum(math.exp(-age / tau_days) for hit, _, age in rows if hit)
        decayed = (wh_sum + alpha) / (w_sum + alpha + beta)
        session.add(SourceAssetScore(
            source_id=sid, asset=asset, horizon=horizon, n_claims=n, n_hits=hits,
            hit_rate=hits / n, avg_return=ret_sum / n, decayed_score=decayed,
            updated_at=now))
        r = roll[(sid, horizon)]
        r["n"] += n; r["hits"] += hits; r["ret_sum"] += ret_sum
        r["w_sum"] += w_sum; r["wh_sum"] += wh_sum

    for (sid, horizon), r in roll.items():
        decayed = (r["wh_sum"] + alpha) / (r["w_sum"] + alpha + beta)
        session.add(SourceScore(
            source_id=sid, horizon=horizon, n_claims=r["n"],
            hit_rate=r["hits"] / r["n"], avg_return=r["ret_sum"] / r["n"],
            decayed_score=decayed, updated_at=now))
    session.commit()
