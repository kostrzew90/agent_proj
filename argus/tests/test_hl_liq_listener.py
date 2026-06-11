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
    """One liq fill + one normal fill in same event -> only liq returned."""
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
