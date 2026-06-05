from datetime import datetime, timezone, timedelta
from argus.models import Asset, Liquidation
from argus.liquidations.cleanup import prune_liquidations

def test_prune_removes_old_keeps_recent(session):
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    now = datetime.now(timezone.utc)
    session.add(Liquidation(asset="BTC", exchange="binance", side="long_liq", price=1, qty=1,
                            notional_usd=1, ts=now - timedelta(days=40), raw_symbol="BTCUSDT", created_at=now))
    session.add(Liquidation(asset="BTC", exchange="binance", side="long_liq", price=1, qty=1,
                            notional_usd=1, ts=now - timedelta(days=2), raw_symbol="BTCUSDT", created_at=now))
    session.commit()
    removed = prune_liquidations(session, days=30)
    assert removed == 1
    assert session.query(Liquidation).count() == 1
