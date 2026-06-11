from datetime import datetime, timezone
import pytest
from argus.liquidations.hl_listener import parse_hl_liquidation


def _event(lid=42, coin="BTC", side_dir="Liquidated Long", px="60000", sz="0.5", ts_ms=1700000000000):
    return {
        "channel": "userEvents",
        "data": {
            "fills": [
                {
                    "coin": coin,
                    "px": px,
                    "sz": sz,
                    "side": "A",
                    "time": ts_ms,
                    "dir": side_dir,
                    "closedPnl": "-1000.0",
                    "liquidationId": lid,
                    "hash": "0xabc",
                    "oid": 123,
                    "crossed": True,
                    "fee": "1.5",
                    "tid": 456,
                    "feeToken": "USDC",
                }
            ]
        },
    }


def _non_liq_event():
    return {
        "channel": "userEvents",
        "data": {
            "fills": [
                {
                    "coin": "BTC",
                    "px": "61000",
                    "sz": "0.1",
                    "side": "B",
                    "time": 1700000000000,
                    "dir": "Open Long",
                    "closedPnl": "0",
                    "liquidationId": None,
                    "hash": "0xdef",
                    "oid": 789,
                    "crossed": False,
                    "fee": "0.5",
                    "tid": 111,
                    "feeToken": "USDC",
                }
            ]
        },
    }


def test_parse_returns_liquidation_fill():
    recs = parse_hl_liquidation(_event(), {"BTC"})
    assert len(recs) == 1
    r = recs[0]
    assert r["asset"] == "BTC"
    assert r["exchange"] == "hyperliquid"
    assert r["side"] == "long_liq"
    assert r["price"] == 60000.0
    assert r["qty"] == 0.5
    assert r["notional_usd"] == pytest.approx(30000.0)
    assert r["raw_symbol"] == "HL_LIQ:42"
    assert isinstance(r["ts"], datetime)
    assert r["ts"].tzinfo is not None


def test_parse_short_liquidation():
    recs = parse_hl_liquidation(_event(side_dir="Liquidated Short"), {"BTC"})
    assert recs[0]["side"] == "short_liq"


def test_parse_skips_non_liquidation_fill():
    recs = parse_hl_liquidation(_non_liq_event(), {"BTC"})
    assert recs == []


def test_parse_skips_unknown_coin():
    recs = parse_hl_liquidation(_event(coin="SOL"), {"BTC", "ETH"})
    assert recs == []


def test_parse_empty_fills():
    event = {"channel": "userEvents", "data": {"fills": []}}
    recs = parse_hl_liquidation(event, {"BTC"})
    assert recs == []


def test_parse_no_fills_key():
    event = {"channel": "userEvents", "data": {}}
    recs = parse_hl_liquidation(event, {"BTC"})
    assert recs == []


def test_parse_mixed_fills():
    event = {
        "channel": "userEvents",
        "data": {
            "fills": [
                _event(lid=1)["data"]["fills"][0],
                _non_liq_event()["data"]["fills"][0],
            ]
        },
    }
    recs = parse_hl_liquidation(event, {"BTC"})
    assert len(recs) == 1
    assert recs[0]["raw_symbol"] == "HL_LIQ:1"

def test_parse_zero_liquidation_id_is_valid():
    recs = parse_hl_liquidation(_event(lid=0), {"BTC"})
    assert len(recs) == 1
    assert recs[0]["raw_symbol"] == "HL_LIQ:0"

from argus.models import Asset, Liquidation, Source, WalletPosition
from argus.liquidations.hl_listener import insert_hl_liquidations


def _btc(session):
    a = Asset(symbol="BTC", kind="crypto", scorable=True)
    session.add(a)
    session.commit()
    return a


def _rec(lid=1, asset="BTC"):
    from datetime import datetime, timezone
    return {
        "asset": asset,
        "exchange": "hyperliquid",
        "side": "long_liq",
        "price": 60000.0,
        "qty": 0.5,
        "notional_usd": 30000.0,
        "raw_symbol": f"HL_LIQ:{lid}",
        "ts": datetime.now(timezone.utc),
    }


def test_insert_basic(session):
    _btc(session)
    n = insert_hl_liquidations(session, [_rec(lid=1)])
    assert n == 1
    row = session.query(Liquidation).one()
    assert row.asset == "BTC"
    assert row.exchange == "hyperliquid"
    assert row.side == "long_liq"
    assert row.raw_symbol == "HL_LIQ:1"
    assert row.created_at is not None


def test_insert_dedup_same_lid(session):
    _btc(session)
    insert_hl_liquidations(session, [_rec(lid=7)])
    n = insert_hl_liquidations(session, [_rec(lid=7)])
    assert n == 0
    assert session.query(Liquidation).count() == 1


def test_insert_different_lids(session):
    _btc(session)
    insert_hl_liquidations(session, [_rec(lid=1)])
    insert_hl_liquidations(session, [_rec(lid=2)])
    assert session.query(Liquidation).count() == 2


def test_insert_empty(session):
    n = insert_hl_liquidations(session, [])
    assert n == 0


def test_wallet_positions_not_modified(session):
    from datetime import datetime, timezone
    _btc(session)
    src = Source(handle="0xabc", kind="hyperliquid", display_name="test", active=True)
    session.add(src)
    session.commit()
    wp = WalletPosition(
        source_id=src.id, coin="BTC", side="long",
        szi=0.5, entry_px=60000.0, position_value=30000.0,
        opened_ts=datetime.now(timezone.utc),
        last_seen_ts=datetime.now(timezone.utc), open=True,
    )
    session.add(wp)
    session.commit()
    insert_hl_liquidations(session, [_rec(lid=99)])
    session.refresh(wp)
    assert wp.open is True


import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from argus.liquidations.hl_listener import _load_wallets, _load_known_assets


def test_load_wallets(session):
    session.add(Source(handle="0xaaa", kind="hyperliquid", active=True, display_name="a"))
    session.add(Source(handle="0xbbb", kind="hyperliquid", active=True, display_name="b"))
    session.add(Source(handle="0xccc", kind="rss", active=True, display_name="c"))
    session.add(Source(handle="0xddd", kind="hyperliquid", active=False, display_name="d"))
    session.commit()
    addrs = _load_wallets(session)
    assert addrs == {"0xaaa", "0xbbb"}


def test_load_known_assets(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True))
    session.add(Asset(symbol="TOTAL", kind="index", scorable=False))
    session.commit()
    assets = _load_known_assets(session)
    assert "BTC" in assets
    assert "TOTAL" in assets


def test_wallet_task_reconnects():
    connect_count = 0

    async def fake_connect(*args, **kwargs):
        nonlocal connect_count
        connect_count += 1
        if connect_count == 1:
            raise ConnectionError("forced")
        ws = AsyncMock()
        ws.__aenter__ = AsyncMock(return_value=ws)
        ws.__aexit__ = AsyncMock(return_value=False)
        ws.send = AsyncMock()
        ws.recv = AsyncMock(side_effect=asyncio.CancelledError())
        return ws

    async def run_task():
        from argus.liquidations.hl_listener import _wallet_task
        try:
            await asyncio.wait_for(
                _wallet_task("0xabc", frozenset({"BTC"})),
                timeout=0.3,
            )
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

    with patch("argus.liquidations.hl_listener.websockets.connect", side_effect=fake_connect), \
         patch("argus.liquidations.hl_listener.SessionLocal") as mock_sl, \
         patch("argus.liquidations.hl_listener.asyncio.sleep", new_callable=AsyncMock):
        mock_s = MagicMock()
        mock_s.__enter__ = MagicMock(return_value=mock_s)
        mock_s.__exit__ = MagicMock(return_value=False)
        mock_s.scalar.return_value = None
        mock_sl.return_value = mock_s
        asyncio.run(run_task())

    assert connect_count >= 2
