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
    assert PARSER_VERSION == "rule-v2"

STOCKS = [Asset(symbol="NFE", kind="stock"), Asset(symbol="DLNG", kind="stock"),
          Asset(symbol="BTC", kind="crypto")]

def test_calls_is_bull():
    c = extract_claims("loading $NFE calls", STOCKS)
    assert c[0].asset_symbol == "NFE" and c[0].direction == "bull"

def test_puts_is_bear():
    c = extract_claims("buying $NFE puts here", STOCKS)
    assert c[0].direction == "bear"

def test_short_squeeze_is_bull_not_bear():
    c = extract_claims("massive short squeeze on BTC", ASSETS)
    assert c[0].asset_symbol == "BTC" and c[0].direction == "bull"

def test_bloodbath_is_bear():
    c = extract_claims("ETH bloodbath today", ASSETS)
    assert c[0].direction == "bear"

def test_cashtag_with_punctuation():
    assert extract_claims("($NFE) calls", STOCKS)[0].asset_symbol == "NFE"
    assert extract_claims("$NFE.. mooning", STOCKS)[0].asset_symbol == "NFE"

def test_sector_association_low_confidence():
    smap = {"natural_gas": {"aliases": ["natural gas", "lng"], "tickers": ["NFE", "DLNG"], "confidence": 0.3}}
    out = extract_claims("natural gas looking bullish", STOCKS, sector_map=smap)
    by = {c.asset_symbol: c for c in out}
    assert set(by) == {"NFE", "DLNG"}
    assert by["NFE"].direction == "bull" and by["NFE"].confidence == 0.3

def test_direct_beats_sector_no_dup():
    smap = {"natural_gas": {"aliases": ["natural gas"], "tickers": ["NFE", "DLNG"], "confidence": 0.3}}
    out = extract_claims("$NFE calls — natural gas bullish", STOCKS, sector_map=smap)
    nfe = [c for c in out if c.asset_symbol == "NFE"]
    assert len(nfe) == 1 and nfe[0].confidence > 0.3
    assert any(c.asset_symbol == "DLNG" and c.confidence == 0.3 for c in out)

def test_sector_only_no_direct_symbol():
    smap = {"natural_gas": {"aliases": ["natural gas"], "tickers": ["NFE", "DLNG"], "confidence": 0.3}}
    out = extract_claims("natural gas is dumping", STOCKS, sector_map=smap)
    assert {c.asset_symbol for c in out} == {"NFE", "DLNG"}
    assert all(c.direction == "bear" for c in out)
