from unittest.mock import patch, MagicMock
from argus.hyperliquid import fetch_positions

def _resp(payload):
    r = MagicMock(); r.raise_for_status.return_value = None; r.json.return_value = payload; return r

def test_parses_long_and_short_and_skips_zero():
    payload = {
        "marginSummary": {"accountValue": "10000.0"},
        "assetPositions": [
            {"position": {"coin": "BTC", "szi": "0.5", "entryPx": "66000.0", "positionValue": "33500.0"}},
            {"position": {"coin": "ETH", "szi": "-2.0", "entryPx": "1900.0", "positionValue": "3800.0"}},
            {"position": {"coin": "SOL", "szi": "0.0", "entryPx": "150.0", "positionValue": "0.0"}},
        ],
    }
    with patch("argus.hyperliquid.httpx.post", return_value=_resp(payload)) as p:
        out = fetch_positions("0xabc")
    assert out["equity"] == 10000.0
    coins = {x["coin"]: x for x in out["positions"]}
    assert set(coins) == {"BTC", "ETH"}
    assert coins["BTC"]["side"] == "long" and coins["BTC"]["position_value"] == 33500.0
    assert coins["ETH"]["side"] == "short"
    assert p.call_args.kwargs["json"] == {"type": "clearinghouseState", "user": "0xabc"}
