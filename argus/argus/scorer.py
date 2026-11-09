import logging
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from sqlalchemy import select, delete
from argus.models import Claim, Outcome, SourceAssetScore, SourceScore

logger = logging.getLogger(__name__)

TAU_BY_HORIZON = {"1h": 14, "24h": 14, "7d": 30, "30d": 120}
_DEFAULT_TAU = 14
_PRIOR_K = 4
_COHORT_SHRINK_HITS = 10
_COHORT_SHRINK_N = 20
_LOO_MIN_GROUP = 20

_GRADE_THRESHOLDS = [
    (0.15, "S"),
    (0.08, "A"),
    (0.03, "B"),
    (-0.03, "C"),
]

def argus_grade(decayed_score: float, n_claims: int, cohort_rate: float, min_claims: int = 5) -> str:
    """Letter grade from the excess of decayed_score over the source's cohort baseline.
    '?' until min_claims reached."""
    if n_claims < min_claims:
        return "?"
    excess = decayed_score - cohort_rate
    for threshold, letter in _GRADE_THRESHOLDS:
        if excess >= threshold:
            return letter
    return "D"

def _age_days(now: datetime, entry_ts: datetime) -> float:
    ets = entry_ts if entry_ts.tzinfo else entry_ts.replace(tzinfo=timezone.utc)
    return (now - ets).total_seconds() / 86400.0

def _cohort_rate(cohort_tot: dict, cohort_own: dict, key: tuple, source_id: int) -> float:
    """Leave-one-out cohort hit-rate with cold-start shrinkage toward 0.5."""
    zero = {"n": 0, "hits": 0}
    tot = cohort_tot.get(key, zero)
    own = cohort_own.get((key, source_id), zero)
    n = tot["n"] - own["n"]
    hits = tot["hits"] - own["hits"]
    if n < _LOO_MIN_GROUP:
        return 0.5
    return (hits + _COHORT_SHRINK_HITS) / (n + _COHORT_SHRINK_N)

def _method_for_group(rows: list) -> str:
    # a group's rows share (source, asset/., horizon, direction); in practice a source runs a
    # single method, but pick the modal one so a theoretical mix doesn't crash cohort lookup.
    return Counter(r["method"] for r in rows).most_common(1)[0][0]

def _decayed_score(rows: list, tau: float, p_c: float) -> float:
    w_sum = sum(math.exp(-r["age"] / tau) for r in rows)
    wh_sum = sum(math.exp(-r["age"] / tau) for r in rows if r["hit"])
    a = p_c * _PRIOR_K
    b = (1 - p_c) * _PRIOR_K
    return (wh_sum + a) / (w_sum + a + b)

def recompute_scores(session, *, k_min: int = 5) -> None:
    now = datetime.now(timezone.utc)

    claims = {c.id: c for c in session.scalars(select(Claim))}

    # one row per outcome; outcomes whose claim no longer exists are skipped
    rows = []
    for o in session.scalars(select(Outcome)):
        c = claims.get(o.claim_id)
        if c is None:
            continue
        rows.append({
            "source_id": c.source_id,
            "asset": c.asset,
            "horizon": o.horizon,
            "method": c.method,
            "direction": c.direction,
            "hit": o.hit,
            "return_pct": o.return_pct,
            "age": _age_days(now, c.entry_ts),
        })

    # cohort aggregates keyed by (method, horizon, direction) -> {n, hits}, plus the same
    # aggregate broken down per source_id, needed for leave-one-out. The "all" direction
    # bucket is fed by every row regardless of that row's own direction.
    cohort_tot = defaultdict(lambda: {"n": 0, "hits": 0})
    cohort_own = defaultdict(lambda: {"n": 0, "hits": 0})

    def _bump(key, source_id, hit):
        cohort_tot[key]["n"] += 1
        cohort_tot[key]["hits"] += 1 if hit else 0
        own = cohort_own[(key, source_id)]
        own["n"] += 1
        own["hits"] += 1 if hit else 0

    for r in rows:
        _bump((r["method"], r["horizon"], r["direction"]), r["source_id"], r["hit"])
        _bump((r["method"], r["horizon"], "all"), r["source_id"], r["hit"])

    def cohort_rate(key, source_id):
        return _cohort_rate(cohort_tot, cohort_own, key, source_id)

    session.execute(delete(SourceAssetScore))
    session.execute(delete(SourceScore))

    # result groups: (source, asset, horizon, direction) and (source, horizon, direction),
    # direction in {bull, bear, all}. Only bull/bear rows feed these — the "all" row aggregates
    # bull+bear for that source (a bare "neutral" claim direction has no own scored row).
    asset_groups = defaultdict(list)
    source_groups = defaultdict(list)
    for r in rows:
        if r["direction"] not in ("bull", "bear"):
            continue
        asset_groups[(r["source_id"], r["asset"], r["horizon"], r["direction"])].append(r)
        asset_groups[(r["source_id"], r["asset"], r["horizon"], "all")].append(r)
        source_groups[(r["source_id"], r["horizon"], r["direction"])].append(r)
        source_groups[(r["source_id"], r["horizon"], "all")].append(r)

    for (sid, asset, horizon, direction), grows in asset_groups.items():
        tau = TAU_BY_HORIZON.get(horizon, _DEFAULT_TAU)
        method = _method_for_group(grows)
        p_c = cohort_rate((method, horizon, direction), sid)
        decayed = _decayed_score(grows, tau, p_c)
        n = len(grows)
        hits = sum(1 for r in grows if r["hit"])
        ret_sum = sum(r["return_pct"] for r in grows)
        session.add(SourceAssetScore(
            source_id=sid, asset=asset, horizon=horizon, direction=direction,
            n_claims=n, n_hits=hits, hit_rate=hits / n, avg_return=ret_sum / n,
            decayed_score=decayed, cohort_rate=p_c, updated_at=now))

    for (sid, horizon, direction), grows in source_groups.items():
        tau = TAU_BY_HORIZON.get(horizon, _DEFAULT_TAU)
        method = _method_for_group(grows)
        p_c = cohort_rate((method, horizon, direction), sid)
        decayed = _decayed_score(grows, tau, p_c)
        n = len(grows)
        hits = sum(1 for r in grows if r["hit"])
        ret_sum = sum(r["return_pct"] for r in grows)
        session.add(SourceScore(
            source_id=sid, horizon=horizon, direction=direction,
            n_claims=n, hit_rate=hits / n, avg_return=ret_sum / n,
            decayed_score=decayed, cohort_rate=p_c, updated_at=now))

    session.commit()
