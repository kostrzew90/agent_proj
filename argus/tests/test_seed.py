import yaml
from argus.seed import seed_assets, seed_sources
from argus.models import Asset, Source

def test_seed_idempotent(session, tmp_path):
    wl = tmp_path / "wl.yaml"
    wl.write_text(yaml.safe_dump({"assets": [
        {"symbol": "BTC", "kind": "crypto", "coingecko_id": "bitcoin",
         "binance_symbol": "BTCUSDT", "scorable": True}]}))
    sr = tmp_path / "sr.yaml"
    sr.write_text(yaml.safe_dump({"sources": [
        {"kind": "rss", "handle": "http://x", "display_name": "X"}]}))
    seed_assets(session, str(wl)); seed_sources(session, str(sr))
    seed_assets(session, str(wl)); seed_sources(session, str(sr))  # 2x
    assert session.query(Asset).count() == 1
    assert session.query(Source).count() == 1
    assert session.query(Asset).one().scorable is True
