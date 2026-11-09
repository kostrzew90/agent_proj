from datetime import timezone
from argus.liquidations.parser import parse_force_order

SMAP = {"BTCUSDT": "BTC", "ETHUSDT": "ETH"}

def _msg(symbol, side, p, q, t=1717500000000):
    return {"e": "forceOrder", "o": {"s": symbol, "S": side, "p": p, "q": q, "X": "FILLED", "T": t}}

def test_sell_is_long_liq_and_strings_parsed():
    r = parse_force_order(_msg("BTCUSDT", "SELL", "67000.0", "1.5"), SMAP)
    assert r["asset"] == "BTC" and r["side"] == "long_liq"
    assert r["price"] == 67000.0 and r["qty"] == 1.5
    assert r["notional_usd"] == 67000.0 * 1.5
    assert r["raw_symbol"] == "BTCUSDT"
    assert r["ts"].tzinfo == timezone.utc

def test_buy_is_short_liq():
    assert parse_force_order(_msg("ETHUSDT", "BUY", "1900", "10"), SMAP)["side"] == "short_liq"

def test_case_insensitive_symbol():
    assert parse_force_order(_msg("btcusdt", "SELL", "1", "1"), SMAP)["asset"] == "BTC"

def test_unknown_symbol_returns_none():
    assert parse_force_order(_msg("DOGEUSDT", "SELL", "1", "1"), SMAP) is None

def test_missing_o_returns_none():
    assert parse_force_order({"e": "x"}, SMAP) is None
