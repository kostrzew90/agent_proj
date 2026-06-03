from datetime import datetime, timezone
from argus.models import Asset, Source, Claim, SourceAssetScore
from argus.analytics import trend_lean

def test_lean_weighted_by_credibility_and_confidence(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True))
    s = Source(kind="rss", handle="h", display_name="D"); session.add(s); session.flush()
    now = datetime.now(timezone.utc)
    session.add(Claim(source_id=s.id, asset="BTC", direction="bull", confidence=0.8,
                      method="rule", entry_price=100.0, entry_ts=now, status="open"))
    session.add(SourceAssetScore(source_id=s.id, asset="BTC", horizon="24h",
                                 n_claims=10, n_hits=8, hit_rate=0.8, avg_return=0.03,
                                 decayed_score=0.75, updated_at=now))
    session.commit()
    rows = trend_lean(session, "24h")
    btc = next(r for r in rows if r["asset"] == "BTC")
    assert btc["lean"] > 0
    assert abs(btc["lean"] - (0.75 * 0.8)) < 0.05

def test_closed_claims_excluded(session):
    session.add(Asset(symbol="ETH", kind="crypto", scorable=True))
    s = Source(kind="rss", handle="h2", display_name="D2"); session.add(s); session.flush()
    now = datetime.now(timezone.utc)
    session.add(Claim(source_id=s.id, asset="ETH", direction="bull", confidence=0.9,
                      method="rule", entry_price=100.0, entry_ts=now, status="closed"))
    session.commit()
    rows = trend_lean(session, "24h")
    assert all(r["asset"] != "ETH" for r in rows)
