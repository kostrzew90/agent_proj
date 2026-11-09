import httpx
import pytest
from unittest.mock import patch, MagicMock
from argus.hyperliquid import fetch_positions


def _r(status, headers=None, payload=None):
    r = MagicMock()
    r.status_code = status
    r.headers = headers or {}
    r.json.return_value = payload or {}
    if status >= 400:
        r.raise_for_status.side_effect = httpx.HTTPStatusError("err", request=MagicMock(), response=r)
    else:
        r.raise_for_status.return_value = None
    return r


def test_429_then_200_sleeps_once():
    with patch("argus.hyperliquid.httpx.post", side_effect=[_r(429), _r(200, payload={"marginSummary": {"accountValue": "5"}})]), \
         patch("argus.hyperliquid.time.sleep") as sl:
        out = fetch_positions("0x1")
    assert out["equity"] == 5.0
    sl.assert_called_once_with(2.0)


def test_429_twice_raises():
    with patch("argus.hyperliquid.httpx.post", side_effect=[_r(429), _r(429)]), \
         patch("argus.hyperliquid.time.sleep"):
        with pytest.raises(httpx.HTTPStatusError):
            fetch_positions("0x1")


def test_retry_after_capped_at_10():
    with patch("argus.hyperliquid.httpx.post", side_effect=[_r(429, {"Retry-After": "30"}), _r(200)]), \
         patch("argus.hyperliquid.time.sleep") as sl:
        fetch_positions("0x1")
    sl.assert_called_once_with(10.0)


def test_retry_after_used_when_small():
    with patch("argus.hyperliquid.httpx.post", side_effect=[_r(429, {"Retry-After": "3"}), _r(200)]), \
         patch("argus.hyperliquid.time.sleep") as sl:
        fetch_positions("0x1")
    sl.assert_called_once_with(3.0)


def test_200_no_sleep():
    with patch("argus.hyperliquid.httpx.post", return_value=_r(200)), \
         patch("argus.hyperliquid.time.sleep") as sl:
        fetch_positions("0x1")
    sl.assert_not_called()
