from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from argus.models import Asset, Claim, Outcome
from argus.prices import get_historical_price

HORIZONS = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}
THRESHOLDS = {"1h": 0.005, "24h": 0.015, "7d": 0.04, "30d": 0.08}

# Which horizons make sense per claim method.
# Insider buying is a 30d+ thesis — 1h/24h/7d would just be noise + leakage.
# Unknown methods default to all horizons (safe fallback).
HORIZONS_BY_METHOD: dict[str, set[str]] = {
    "insider":  {"30d"},
    "position": {"24h", "7d", "30d"},
    "rule":     {"1h", "24h", "7d"},
    "llm":      {"1h", "24h", "7d"},
}

def _hit(direction: str, ret: float, thr: float) -> bool:
    if direction == "bull":
        return ret >= thr
    if direction == "bear":
        return ret <= -thr
    return abs(ret) < thr  # neutral

def evaluate_due_claims(session, now: datetime) -> int:
    claims = list(session.scalars(select(Claim).where(Claim.status != "closed")))
    assets = {a.symbol: a for a in session.scalars(select(Asset))}
    done = {(o.claim_id, o.horizon) for o in session.scalars(select(Outcome))}
    created = 0
    for c in claims:
        asset = assets.get(c.asset)
        if asset is None or not asset.scorable:
            continue
        entry_ts = c.entry_ts if c.entry_ts.tzinfo else c.entry_ts.replace(tzinfo=timezone.utc)
        allowed_horizons = HORIZONS_BY_METHOD.get(c.method, set(HORIZONS.keys()))
        for h, delta in HORIZONS.items():
            if h not in allowed_horizons:
                continue
            if (c.id, h) in done:
                continue
            if now < entry_ts + delta:
                continue
            price = get_historical_price(asset, entry_ts + delta)
            ret = (price - c.entry_price) / c.entry_price
            session.add(Outcome(claim_id=c.id, horizon=h, eval_ts=now,
                                price_at_horizon=price, return_pct=ret,
                                hit=_hit(c.direction, ret, THRESHOLDS[h]),
                                resolved_at=now))
            created += 1
        if now >= entry_ts + HORIZONS["30d"]:
            c.status = "closed"
    session.commit()
    return created
