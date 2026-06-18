import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argus.liquidations.hl_listener import (
    _load_known_assets,
    _load_wallets,
    _poll_all,
    insert_hl_liquidations,
    parse_hl_liquidation,
)
from argus.models import Asset, Liquidation, Source, WalletPosition


# ─── helpers ────────────────────────────────────────────────────────────────

def _fill(lid=42, coin="BTC", side_dir="Liquidated Long", px="60000", sz="0.5", ts_ms=1700000000000):
    return {
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


def _non_liq_fill():
    return {
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


def _rec(lid=1, asset="BTC"):
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


def _btc(session):
    a = Asset(symbol="BTC", kind="crypto", scorable=True)
    session.add(a)
    session.commit()
    return a


# ─── parse_hl_liquidation ────────────────────────────────────────────────────

def test_parse_returns_liquidation_fill():
    recs = parse_hl_liquidation([_fill()], {"BTC"})
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
    recs = parse_hl_liquidation([_fill(side_dir="Liquidated Short")], {"BTC"})
    assert recs[0]["side"] == "short_liq"


def test_parse_skips_non_liquidation_fill():
    recs = parse_hl_liquidation([_non_liq_fill()], {"BTC"})
    assert recs == []


def test_parse_skips_unknown_coin():
    recs = parse_hl_liquidation([_fill(coin="SOL")], {"BTC", "ETH"})
    assert recs == []


def test_parse_empty_fills():
    recs = parse_hl_liquidation([], {"BTC"})
    assert recs == []


def test_parse_mixed_fills():
    recs = parse_hl_liquidation([_fill(lid=1), _non_liq_fill()], {"BTC"})
    assert len(recs) == 1
    assert recs[0]["raw_symbol"] == "HL_LIQ:1"


def test_parse_zero_liquidation_id_is_valid():
    recs = parse_hl_liquidation([_fill(lid=0)], {"BTC"})
    assert len(recs) == 1
    assert recs[0]["raw_symbol"] == "HL_LIQ:0"


# ─── insert_hl_liquidations ──────────────────────────────────────────────────

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


def test_insert_batch_partial_dedup(session):
    """When batch has mix of new and existing lids, only new ones are inserted."""
    _btc(session)
    insert_hl_liquidations(session, [_rec(lid=1)])
    n = insert_hl_liquidations(session, [_rec(lid=1), _rec(lid=2)])
    assert n == 1
    assert session.query(Liquidation).count() == 2


def test_insert_empty(session):
    n = insert_hl_liquidations(session, [])
    assert n == 0


def test_wallet_positions_not_modified(session):
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


# ─── _load_wallets / _load_known_assets ──────────────────────────────────────

def test_load_wallets(session):
    session.add(Source(handle="0xaaa", kind="hyperliquid", active=True, display_name="a"))
    session.add(Source(handle="0xbbb", kind="hyperliquid", active=True, display_name="b"))
    session.add(Source(handle="0xccc", kind="rss", active=True, display_name="c"))
    session.add(Source(handle="0xddd", kind="hyperliquid", active=False, display_name="d"))
    session.commit()
    addrs = _load_wallets(session)
    assert set(addrs) == {"0xaaa", "0xbbb"}


def test_load_known_assets(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True))
    session.add(Asset(symbol="TOTAL", kind="index", scorable=False))
    session.commit()
    assets = _load_known_assets(session)
    assert "BTC" in assets
    assert "TOTAL" in assets


# ─── _poll_all ───────────────────────────────────────────────────────────────

def test_poll_all_returns_sum_of_inserts():
    async def run():
        async def fake_poll_wallet(client, sem, addr, known_assets):
            return {"0xaaa": 2, "0xbbb": 0, "0xccc": 1}.get(addr, 0)

        with patch("argus.liquidations.hl_listener._poll_wallet", side_effect=fake_poll_wallet):
            return await _poll_all(["0xaaa", "0xbbb", "0xccc"], frozenset({"BTC"}))

    total = asyncio.run(run())
    assert total == 3


def test_poll_all_skips_erroring_wallet():
    async def run():
        async def fake_poll_wallet(client, sem, addr, known_assets):
            if addr == "0xbad":
                raise RuntimeError("network error")
            return 1

        with patch("argus.liquidations.hl_listener._poll_wallet", side_effect=fake_poll_wallet):
            return await _poll_all(["0xgood", "0xbad"], frozenset({"BTC"}))

    total = asyncio.run(run())
    assert total == 1


def test_poll_all_empty_wallets():
    total = asyncio.run(_poll_all([], frozenset({"BTC"})))
    assert total == 0
