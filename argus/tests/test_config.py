import yaml

def test_sources_have_reddit_and_news():
    data = yaml.safe_load(open("config/sources.yaml", encoding="utf-8"))
    kinds = {s["kind"] for s in data["sources"]}
    assert {"rss", "reddit", "news"} <= kinds
    handles = [s["handle"] for s in data["sources"]]
    assert any("reddit.com" in h for h in handles)

def test_sectors_structure_and_known_tickers():
    data = yaml.safe_load(open("config/sectors.yaml", encoding="utf-8"))
    watchlist_stocks = {"XOMA", "BYND", "DLNG", "LCID", "NFE", "NTR", "PLG"}
    for key, sec in data.items():
        assert sec["aliases"] and sec["tickers"]
        assert isinstance(sec["confidence"], (int, float))
        assert set(sec["tickers"]) <= watchlist_stocks, f"{key} has unknown ticker"
