from unittest.mock import patch
from argus.models import Asset, Source, Claim, ClaimAudit, WalletPosition
from argus.collectors.hyperliquid import collect_wallet

def _seed(session):
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    s = Source(kind="hyperliquid", handle="0xabc", display_name="w1"); session.add(s); session.commit()
    return s

def _data(positions, equity=10000.0):
    return {"equity": equity, "positions": positions}

def test_new_watchlist_long_creates_bull_claim(session):
    s = _seed(session)
    pos = [{"coin": "BTC", "side": "long", "szi": 0.1, "entry_px": 66000.0, "position_value": 8000.0}]
    with patch("argus.collectors.hyperliquid.fetch_positions", return_value=_data(pos)), \
         patch("argus.collectors.hyperliquid.get_spot_price", return_value=67000.0):
        n = collect_wallet(session, s)
    assert n == 1
    c = session.query(Claim).one()
    assert c.asset == "BTC" and c.direction == "bull" and c.method == "position"
    assert c.entry_price == 67000.0
    assert abs(c.confidence - 0.8) < 1e-9
    assert session.query(WalletPosition).filter_by(coin="BTC", open=True).count() == 1
    assert session.query(ClaimAudit).one().parser_version == "hyperliquid-v1"

def test_no_change_no_new_claim(session):
    s = _seed(session)
    pos = [{"coin": "BTC", "side": "long", "szi": 0.1, "entry_px": 66000.0, "position_value": 8000.0}]
    with patch("argus.collectors.hyperliquid.fetch_positions", return_value=_data(pos)), \
         patch("argus.collectors.hyperliquid.get_spot_price", return_value=67000.0):
        collect_wallet(session, s)
        collect_wallet(session, s)
    assert session.query(Claim).count() == 1

def test_flip_creates_new_claim(session):
    s = _seed(session)
    with patch("argus.collectors.hyperliquid.get_spot_price", return_value=67000.0):
        with patch("argus.collectors.hyperliquid.fetch_positions",
                   return_value=_data([{"coin":"BTC","side":"long","szi":0.1,"entry_px":66000.0,"position_value":8000.0}])):
            collect_wallet(session, s)
        with patch("argus.collectors.hyperliquid.fetch_positions",
                   return_value=_data([{"coin":"BTC","side":"short","szi":-0.1,"entry_px":67000.0,"position_value":8000.0}])):
            collect_wallet(session, s)
    dirs = sorted(c.direction for c in session.query(Claim).all())
    assert dirs == ["bear", "bull"]
    assert session.query(WalletPosition).filter_by(coin="BTC").one().side == "short"

def test_off_watchlist_records_position_no_claim(session):
    s = _seed(session)
    pos = [{"coin": "HYPE", "side": "long", "szi": 100.0, "entry_px": 20.0, "position_value": 2000.0}]
    with patch("argus.collectors.hyperliquid.fetch_positions", return_value=_data(pos)), \
         patch("argus.collectors.hyperliquid.get_spot_price", return_value=67000.0):
        collect_wallet(session, s)
    assert session.query(Claim).count() == 0
    assert session.query(WalletPosition).filter_by(coin="HYPE", open=True).count() == 1

def test_confidence_fallback_when_no_equity(session):
    s = _seed(session)
    pos = [{"coin": "BTC", "side": "long", "szi": 0.1, "entry_px": 66000.0, "position_value": 8000.0}]
    with patch("argus.collectors.hyperliquid.fetch_positions", return_value=_data(pos, equity=0.0)), \
         patch("argus.collectors.hyperliquid.get_spot_price", return_value=67000.0):
        collect_wallet(session, s)
    assert abs(session.query(Claim).one().confidence - 0.7) < 1e-9

def test_consensus_emits_claim_when_supermajority(session):
    from datetime import datetime, timezone
    from argus.models import Asset, Source, Claim, WalletPosition
    from argus.collectors.hyperliquid import compute_consensus
    session.add(Asset(symbol="SOL", kind="crypto", binance_symbol="SOLUSDT", scorable=True))
    cons = Source(kind="derived", handle="whale-consensus", display_name="Whale Consensus")
    session.add(cons)
    now = datetime.now(timezone.utc)
    for i in range(6):
        w = Source(kind="hyperliquid", handle=f"0x{i:040x}", display_name=f"w{i}")
        session.add(w); session.flush()
        side = "long" if i < 5 else "short"          # 5/6 long
        session.add(WalletPosition(source_id=w.id, coin="SOL", side=side, szi=1.0, entry_px=150.0,
                                   position_value=1000.0, opened_ts=now, last_seen_ts=now, open=True))
    session.commit()
    with patch("argus.collectors.hyperliquid.get_spot_price", return_value=150.0):
        n = compute_consensus(session, min_wallets=4, ratio=0.66)
    assert n == 1
    c = session.query(Claim).filter_by(source_id=cons.id).one()
    assert c.asset == "SOL" and c.direction == "bull"
    with patch("argus.collectors.hyperliquid.get_spot_price", return_value=150.0):
        assert compute_consensus(session, min_wallets=4, ratio=0.66) == 0   # no change

def test_consensus_below_threshold_no_claim(session):
    from datetime import datetime, timezone
    from argus.models import Asset, Source, WalletPosition
    from argus.collectors.hyperliquid import compute_consensus
    session.add(Asset(symbol="SOL", kind="crypto", binance_symbol="SOLUSDT", scorable=True))
    session.add(Source(kind="derived", handle="whale-consensus", display_name="Whale Consensus"))
    now = datetime.now(timezone.utc)
    for i in range(2):
        w = Source(kind="hyperliquid", handle=f"0x{i:040x}", display_name=f"w{i}"); session.add(w); session.flush()
        session.add(WalletPosition(source_id=w.id, coin="SOL", side="long", szi=1.0, entry_px=150.0,
                                   position_value=1000.0, opened_ts=now, last_seen_ts=now, open=True))
    session.commit()
    with patch("argus.collectors.hyperliquid.get_spot_price", return_value=150.0):
        assert compute_consensus(session, min_wallets=4, ratio=0.66) == 0
