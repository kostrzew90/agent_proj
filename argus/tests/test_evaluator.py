from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from argus.models import Asset, Source, Claim, Outcome
from argus.evaluator import evaluate_due_claims, HORIZONS, THRESHOLDS

def _setup(session, direction, entry=100.0):
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    s = Source(kind="rss", handle="h", display_name="D"); session.add(s); session.flush()
    old = datetime.now(timezone.utc) - timedelta(days=8)  # po wszystkich horyzontach
    c = Claim(source_id=s.id, asset="BTC", direction=direction, confidence=0.8,
              method="rule", entry_price=entry, entry_ts=old, status="open")
    session.add(c); session.commit()
    return c

def test_bull_hit_when_price_up(session):
    _setup(session, "bull")
    with patch("argus.evaluator.get_historical_price", return_value=110.0):
        evaluate_due_claims(session, datetime.now(timezone.utc))
    outs = {o.horizon: o for o in session.query(Outcome).all()}
    assert set(outs) == set(HORIZONS)
    assert all(o.hit for o in outs.values())          # +10% > każdy próg
    assert abs(outs["24h"].return_pct - 0.10) < 1e-6

def test_bear_hit_when_price_down(session):
    _setup(session, "bear")
    with patch("argus.evaluator.get_historical_price", return_value=90.0):
        evaluate_due_claims(session, datetime.now(timezone.utc))
    assert all(o.hit for o in session.query(Outcome).all())

def test_neutral_hit_when_flat(session):
    _setup(session, "neutral")
    with patch("argus.evaluator.get_historical_price", return_value=100.1):
        evaluate_due_claims(session, datetime.now(timezone.utc))
    assert all(o.hit for o in session.query(Outcome).all())  # 0.1% < każdy próg

def test_no_double_eval(session):
    _setup(session, "bull")
    with patch("argus.evaluator.get_historical_price", return_value=110.0):
        evaluate_due_claims(session, datetime.now(timezone.utc))
        evaluate_due_claims(session, datetime.now(timezone.utc))
    assert session.query(Outcome).count() == len(HORIZONS)
