import math
import pytest
from datetime import datetime, timedelta, timezone

from argus.models import Source, Claim, Outcome, SourceAssetScore, SourceScore
from argus.scorer import recompute_scores, argus_grade, TAU_BY_HORIZON, _LOO_MIN_GROUP

_ASSET = "BTC"
_METHOD = "rule"
_HORIZON = "24h"


def _make_source(session, handle):
    s = Source(kind="rss", handle=handle, display_name=handle)
    session.add(s)
    session.commit()
    return s


def _add_claims(session, source, n_hits, n_miss, *, method=_METHOD, horizon=_HORIZON,
                direction="bull", asset=_ASSET, age_days=0.0):
    """Add n_hits winning claims and n_miss losing claims, all resolved on `horizon`."""
    ts = datetime.now(timezone.utc) - timedelta(days=age_days)
    win_ret = 0.05 if direction == "bull" else -0.05
    lose_ret = -0.05 if direction == "bull" else 0.05
    for _ in range(n_hits):
        c = Claim(source_id=source.id, asset=asset, direction=direction, confidence=0.7,
                  method=method, entry_price=100.0, entry_ts=ts, status="closed")
        session.add(c)
        session.flush()
        session.add(Outcome(claim_id=c.id, horizon=horizon, eval_ts=ts,
                            price_at_horizon=100 * (1 + win_ret), return_pct=win_ret, hit=True))
    for _ in range(n_miss):
        c = Claim(source_id=source.id, asset=asset, direction=direction, confidence=0.7,
                  method=method, entry_price=100.0, entry_ts=ts, status="closed")
        session.add(c)
        session.flush()
        session.add(Outcome(claim_id=c.id, horizon=horizon, eval_ts=ts,
                            price_at_horizon=100 * (1 + lose_ret), return_pct=lose_ret, hit=False))
    session.commit()


def _build_cohort(session, raw_rate, *, total=400, direction="bull", label="cohort"):
    """Many small helper sources at a fixed raw hit-rate, large enough that the
    +10/+20 shrinkage barely moves the resulting cohort rate away from `raw_rate`.
    Returns the exact (shrunk) cohort rate as a Fraction, computed the same way
    _cohort_rate() does, so callers can build an exactly-matching hit ratio."""
    from fractions import Fraction
    n_sources = 20
    per_source = total // n_sources
    hits_per = round(per_source * raw_rate)
    for i in range(n_sources):
        s = _make_source(session, f"{label}-{i}")
        _add_claims(session, s, hits_per, per_source - hits_per, direction=direction)
    total_hits = n_sources * hits_per
    return Fraction(total_hits + 10, total + 20)


def _asset_score(session, source_id, direction="bull"):
    return session.query(SourceAssetScore).filter_by(
        source_id=source_id, asset=_ASSET, horizon=_HORIZON, direction=direction).one()


# ---------------------------------------------------------------------------
# 1. Decisive test (kryterium sukcesu z sekcji 2)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("p_c", [0.25, 0.5, 0.7])
def test_decayed_score_monotonic_around_cohort_baseline(session, p_c):
    _build_cohort(session, p_c, label=f"cohort-{p_c}")

    # n's are multiples of 20 so that (p_win*20) and (p_lose*20) below are exact integers —
    # every step then has the SAME true hit-rate, isolating "more observations" as the only
    # variable (avoiding rounding artifacts from round(n*p) landing on different ratios).
    n_list = (20, 60, 140)

    # source that beats the cohort: score must strictly increase with more observations
    winner = _make_source(session, f"winner-{p_c}")
    p_win = min(0.9, p_c + 0.2)
    hits_per_20 = round(p_win * 20)
    scores_up = []
    cum_n = cum_hits = 0
    for n in n_list:
        target_hits = (n // 20) * hits_per_20
        _add_claims(session, winner, target_hits - cum_hits, (n - target_hits) - (cum_n - cum_hits))
        cum_n, cum_hits = n, target_hits
        recompute_scores(session)
        scores_up.append(_asset_score(session, winner.id).decayed_score)
    assert scores_up == sorted(scores_up), f"expected increasing scores, got {scores_up}"
    assert scores_up[0] < scores_up[-1]

    # source that loses to the cohort: score must strictly decrease with more observations
    loser = _make_source(session, f"loser-{p_c}")
    p_lose = max(0.1, p_c - 0.2)
    hits_per_20 = round(p_lose * 20)
    scores_down = []
    cum_n = cum_hits = 0
    for n in n_list:
        target_hits = (n // 20) * hits_per_20
        _add_claims(session, loser, target_hits - cum_hits, (n - target_hits) - (cum_n - cum_hits))
        cum_n, cum_hits = n, target_hits
        recompute_scores(session)
        scores_down.append(_asset_score(session, loser.id).decayed_score)
    assert scores_down == sorted(scores_down, reverse=True), f"expected decreasing scores, got {scores_down}"
    assert scores_down[0] > scores_down[-1]


# ---------------------------------------------------------------------------
# 2. Source at cohort level stays at cohort level regardless of n
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("p_c", [0.25, 0.5, 0.7])
def test_source_at_cohort_rate_stays_flat(session, p_c):
    cohort_rate = _build_cohort(session, p_c, label=f"flat-cohort-{p_c}")
    matched = _make_source(session, f"matched-{p_c}")

    # n's are multiples of cohort_rate's denominator so the matched source's own hit-rate
    # lands EXACTLY on the cohort's (shrunk) baseline at every step, not just approximately
    denom = cohort_rate.denominator
    n_list = (denom, denom * 2, denom * 4)

    scores = []
    cohort_rates_seen = []
    cum_n = cum_hits = 0
    for n in n_list:
        target_hits = (n // denom) * cohort_rate.numerator
        _add_claims(session, matched, target_hits - cum_hits, (n - target_hits) - (cum_n - cum_hits))
        cum_n, cum_hits = n, target_hits
        recompute_scores(session)
        row = _asset_score(session, matched.id)
        scores.append(row.decayed_score)
        cohort_rates_seen.append(row.cohort_rate)

    # the matched source's own hit-rate exactly equals the cohort's (shrunk) baseline at
    # every step, so decayed_score must sit exactly on that baseline regardless of n
    for s, cr in zip(scores, cohort_rates_seen):
        assert abs(s - cr) < 1e-9, f"expected score pinned at cohort baseline {cr}, got {s}"
        assert abs(cr - float(cohort_rate)) < 1e-9


# ---------------------------------------------------------------------------
# 3. Leave-one-out: a source that dominates its cohort can still beat it
# ---------------------------------------------------------------------------

def test_leave_one_out_lets_dominant_source_beat_its_own_cohort(session):
    # minority group: satisfies _LOO_MIN_GROUP on its own, at a mediocre rate
    minority = _make_source(session, "minority")
    _add_claims(session, minority, 6, 14)  # 20 claims @ 30%

    # dominant source: far more claims than the minority, at a much higher rate
    dominant = _make_source(session, "dominant")
    _add_claims(session, dominant, 70, 30)  # 100 claims @ 70%

    recompute_scores(session)

    dom_score = _asset_score(session, dominant.id)
    # LOO cohort for `dominant` excludes its own rows entirely, so its baseline is
    # pulled from the minority group (~30%), not diluted by its own 70%.
    assert dom_score.cohort_rate < 0.5
    assert dom_score.decayed_score > dom_score.cohort_rate


# ---------------------------------------------------------------------------
# 4. Cold start: a tiny cohort shrinks to ~0.5 no matter how extreme its raw rate
# ---------------------------------------------------------------------------

def test_cold_start_cohort_shrinks_to_neutral(session):
    # cohort has only 5 observations total (from a different source than the one we probe)
    tiny_source = _make_source(session, "tiny-cohort-source")
    _add_claims(session, tiny_source, 5, 0, method="llm", horizon="7d", direction="bull")  # 100% raw

    probe = _make_source(session, "probe")
    _add_claims(session, probe, 1, 1, method="llm", horizon="7d", direction="bull")

    recompute_scores(session)

    probe_score = session.query(SourceAssetScore).filter_by(
        source_id=probe.id, asset=_ASSET, horizon="7d", direction="bull").one()
    assert probe_score.cohort_rate == 0.5, (
        f"expected fallback to 0.5 with cohort n=5 < {_LOO_MIN_GROUP}, got {probe_score.cohort_rate}")


# ---------------------------------------------------------------------------
# 5. TAU_BY_HORIZON: weight at settlement time is >= 0.75 for every horizon
# ---------------------------------------------------------------------------

_HORIZON_LENGTH_DAYS = {"1h": 1 / 24, "24h": 1.0, "7d": 7.0, "30d": 30.0}


@pytest.mark.parametrize("horizon,tau", list(TAU_BY_HORIZON.items()))
def test_tau_gives_settlement_weight_at_least_075(horizon, tau):
    age_at_settlement = _HORIZON_LENGTH_DAYS[horizon]
    weight = math.exp(-age_at_settlement / tau)
    assert weight >= 0.75, f"{horizon}: weight {weight:.3f} < 0.75 (tau={tau})"


# ---------------------------------------------------------------------------
# 6. Direction split: bull/bear get separate rows, "all" aggregates both
# ---------------------------------------------------------------------------

def test_bull_bear_split_into_separate_rows_all_aggregates_both(session):
    src = _make_source(session, "mixed-direction")
    _add_claims(session, src, 8, 2, direction="bull")   # 10 bull claims, 8 hits
    _add_claims(session, src, 3, 7, direction="bear")   # 10 bear claims, 3 hits

    recompute_scores(session)

    bull = _asset_score(session, src.id, direction="bull")
    bear = _asset_score(session, src.id, direction="bear")
    allrow = _asset_score(session, src.id, direction="all")

    assert bull.n_claims == 10 and bull.n_hits == 8
    assert bear.n_claims == 10 and bear.n_hits == 3
    assert allrow.n_claims == 20 and allrow.n_hits == 11


# ---------------------------------------------------------------------------
# 7. Relative grading: a source exactly at its cohort baseline gets "C"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("p_c", [0.25, 0.5, 0.7])
def test_grade_at_cohort_baseline_is_c(p_c):
    assert argus_grade(decayed_score=p_c, n_claims=10, cohort_rate=p_c) == "C"
