from datetime import datetime, timezone
from unittest.mock import patch
from argus.models import Asset
from argus.prices import get_spot_price, get_historical_price

def test_crypto_spot_uses_binance():
    a = Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT")
    with patch("argus.prices._gate_spot", side_effect=RuntimeError("down")), \
         patch("argus.prices._binance_spot", return_value=67000.0) as m:
        assert get_spot_price(a) == 67000.0
        m.assert_called_once_with("BTCUSDT")

def test_stock_spot_uses_yf():
    a = Asset(symbol="LCID", kind="stock", yf_symbol="LCID")
    with patch("argus.prices._yf_spot", return_value=6.28) as m:
        assert get_spot_price(a) == 6.28
        m.assert_called_once_with("LCID")

def test_historical_crypto():
    a = Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT")
    when = datetime(2026, 6, 1, tzinfo=timezone.utc)
    with patch("argus.prices._binance_historical", return_value=66000.0):
        assert get_historical_price(a, when) == 66000.0

def test_unsupported_kind_raises():
    a = Asset(symbol="TOTAL", kind="index")
    try:
        get_spot_price(a); assert False
    except ValueError:
        pass


# --- Gate.io futures ---
from datetime import timedelta
from unittest.mock import MagicMock

_BTC = Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT")


def _resp(payload):
    r = MagicMock()
    r.raise_for_status.return_value = None
    r.json.return_value = payload
    return r


def test_gate_spot_ok():
    with patch("argus.prices.httpx.get", return_value=_resp([{"last": "74668"}])) as g, \
         patch("argus.prices._binance_spot") as b:
        assert get_spot_price(_BTC) == 74668.0
    assert g.call_args.kwargs["params"] == {"contract": "BTC_USDT"}
    b.assert_not_called()


def test_gate_spot_error_falls_back_to_binance():
    with patch("argus.prices._gate_spot", side_effect=RuntimeError("boom")), \
         patch("argus.prices._binance_spot", return_value=1.5) as b:
        assert get_spot_price(_BTC) == 1.5
    b.assert_called_once_with("BTCUSDT")


def test_historical_recent_uses_gate_1m():
    when = datetime.now(timezone.utc) - timedelta(days=1)
    with patch("argus.prices.httpx.get", return_value=_resp([{"t": 1, "c": "74069"}])) as g, \
         patch("argus.prices._binance_historical") as b:
        assert get_historical_price(_BTC, when) == 74069.0
    p = g.call_args.kwargs["params"]
    assert p["interval"] == "1m" and p["from"] == int(when.timestamp()) and p["to"] == p["from"] + 60
    b.assert_not_called()


def test_historical_recent_naive_datetime_ok():
    when = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    with patch("argus.prices._gate_historical", return_value=5.0) as gh:
        assert get_historical_price(_BTC, when) == 5.0
    gh.assert_called_once()


def test_historical_old_skips_gate():
    when = datetime.now(timezone.utc) - timedelta(days=10)
    with patch("argus.prices._gate_historical") as gh, \
         patch("argus.prices._binance_historical", return_value=7.0) as b:
        assert get_historical_price(_BTC, when) == 7.0
    gh.assert_not_called()
    b.assert_called_once()


def test_historical_gate_empty_falls_back_to_binance():
    when = datetime.now(timezone.utc) - timedelta(days=1)
    with patch("argus.prices.httpx.get", return_value=_resp([])), \
         patch("argus.prices._binance_historical", return_value=7.0):
        assert get_historical_price(_BTC, when) == 7.0
