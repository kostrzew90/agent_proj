from datetime import datetime, timedelta, timezone
from argus.models import Source, Claim, Outcome, SourceAssetScore, SourceScore
from argus.scorer import recompute_scores

def _claim_with_outcome(session, source_id, asset, hit, ret, age_days=0):
    ts = datetime.now(timezone.utc) - timedelta(days=age_days)
    c = Claim(source_id=source_id, asset=asset, direction="bull", confidence=0.8,
              method="rule", entry_price=100.0, entry_ts=ts, status="closed")
    session.add(c); session.flush()
    session.add(Outcome(claim_id=c.id, horizon="24h", eval_ts=ts,
                        price_at_horizon=100*(1+ret), return_pct=ret, hit=hit))
    session.commit()

def test_perfect_source_high_score(session):
    s = Source(kind="rss", handle="h", display_name="D"); session.add(s); session.commit()
    for _ in range(10):
        _claim_with_outcome(session, s.id, "BTC", hit=True, ret=0.05)
    recompute_scores(session)
    sas = session.query(SourceAssetScore).filter_by(asset="BTC", horizon="24h").one()
    assert sas.n_claims == 10 and sas.n_hits == 10
    assert sas.hit_rate == 1.0
    assert sas.decayed_score > 0.8
    assert abs(sas.avg_return - 0.05) < 1e-6

def test_small_sample_shrinks_to_half(session):
    s = Source(kind="rss", handle="h2", display_name="D2"); session.add(s); session.commit()
    _claim_with_outcome(session, s.id, "ETH", hit=True, ret=0.05)  # n=1
    recompute_scores(session)
    sas = session.query(SourceAssetScore).filter_by(asset="ETH", horizon="24h").one()
    assert 0.5 < sas.decayed_score < 0.8

def test_rollup_source_score_exists(session):
    s = Source(kind="rss", handle="h3", display_name="D3"); session.add(s); session.commit()
    _claim_with_outcome(session, s.id, "BTC", hit=True, ret=0.05)
    _claim_with_outcome(session, s.id, "ETH", hit=False, ret=-0.05)
    recompute_scores(session)
    assert session.query(SourceScore).filter_by(source_id=s.id, horizon="24h").count() == 1
