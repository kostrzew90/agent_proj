from datetime import datetime, timezone
from unittest.mock import patch
from argus.models import Asset
from argus.prices import get_spot_price, get_historical_price

def test_crypto_spot_uses_binance():
    a = Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT")
    with patch("argus.prices._binance_spot", return_value=67000.0) as m:
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
