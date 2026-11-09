from unittest.mock import patch, MagicMock
from argus.models import Asset
from argus.charts import get_candles

def test_crypto_candles_parsed_with_defaults():
    a = Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT")
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = [[1717200000000, "67000.0", "67500.0", "66800.0", "67200.0",
                               "10", 0, 0, 0, 0, 0, 0]]
    with patch("argus.charts._gate_candles", side_effect=RuntimeError("down")), \
         patch("argus.charts.httpx.get", return_value=resp) as g:
        candles = get_candles(a)
    assert candles == [{"time": 1717200000, "open": 67000.0, "high": 67500.0,
                        "low": 66800.0, "close": 67200.0}]
    assert g.call_args.kwargs["params"]["interval"] == "1h"
    assert g.call_args.kwargs["params"]["limit"] == 168
    assert g.call_args.kwargs["params"]["symbol"] == "BTCUSDT"

def test_stock_dispatch_uses_yf_candles():
    a = Asset(symbol="LCID", kind="stock", yf_symbol="LCID")
    sentinel = [{"time": 1, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}]
    with patch("argus.charts._yf_candles", return_value=sentinel) as m:
        out = get_candles(a)
    m.assert_called_once_with("LCID", 90)
    assert out == sentinel

def test_index_kind_raises():
    a = Asset(symbol="TOTAL", kind="index")
    try:
        get_candles(a)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_crypto_candles_from_gate():
    a = Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT")
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = [{"t": 1794171600, "o": "75720", "h": "75760", "l": "73420",
                               "c": "74069", "v": 1, "sum": "2"}]
    with patch("argus.charts.httpx.get", return_value=resp) as g:
        candles = get_candles(a, "4h", 50)
    assert candles == [{"time": 1794171600, "open": 75720.0, "high": 75760.0,
                        "low": 73420.0, "close": 74069.0}]
    assert g.call_args.kwargs["params"] == {"contract": "BTC_USDT", "interval": "4h", "limit": 50}


def test_crypto_candles_gate_error_falls_back_to_binance():
    a = Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT")
    sentinel = [{"time": 1, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}]
    with patch("argus.charts._gate_candles", side_effect=RuntimeError("x")), \
         patch("argus.charts._binance_candles", return_value=sentinel) as b:
        assert get_candles(a) == sentinel
    b.assert_called_once_with("BTCUSDT", "1h", 168)
