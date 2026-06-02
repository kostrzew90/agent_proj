from argus.extract import extract_claims, PARSER_VERSION
from argus.models import Asset

ASSETS = [Asset(symbol="BTC", kind="crypto"), Asset(symbol="ETH", kind="crypto"),
          Asset(symbol="SOL", kind="crypto")]

def test_long_is_bull_high_conf():
    c = extract_claims("Going long BTC, target 100k", ASSETS)
    assert len(c) == 1
    assert c[0].asset_symbol == "BTC"
    assert c[0].direction == "bull"
    assert c[0].confidence >= 0.7
    assert c[0].target_price == 100000.0

def test_bearish_is_bear_low_conf():
    c = extract_claims("I'm a bit bearish on ETH maybe", ASSETS)
    assert c[0].direction == "bear"
    assert c[0].confidence <= 0.5

def test_short_keyword():
    c = extract_claims("short SOL here", ASSETS)
    assert c[0].direction == "bear"

def test_no_asset_no_claim():
    assert extract_claims("market looks interesting today", ASSETS) == []

def test_no_direction_no_claim():
    assert extract_claims("BTC is a cryptocurrency", ASSETS) == []

def test_parser_version_constant():
    assert PARSER_VERSION == "rule-v1"
