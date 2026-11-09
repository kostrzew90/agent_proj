from datetime import datetime, timezone
from argus.models import Asset, Liquidation
from argus.liquidations.listener import load_symbol_map, insert_liquidations

def test_load_symbol_map_uppercased(session):
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    session.add(Asset(symbol="ETH", kind="crypto", binance_symbol="ethusdt", scorable=True))
    session.add(Asset(symbol="TOTAL", kind="index"))   # no binance_symbol -> excluded
    session.commit()
    m = load_symbol_map(session)
    assert m == {"BTCUSDT": "BTC", "ETHUSDT": "ETH"}

def test_insert_liquidations(session):
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    session.commit()
    now = datetime.now(timezone.utc)
    rows = [{"asset": "BTC", "raw_symbol": "BTCUSDT", "side": "long_liq", "price": 67000.0,
             "qty": 1.0, "notional_usd": 67000.0, "ts": now}]
    n = insert_liquidations(session, rows)
    assert n == 1
    assert session.query(Liquidation).one().asset == "BTC"
