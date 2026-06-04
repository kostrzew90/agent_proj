from datetime import datetime, timezone
from unittest.mock import patch
from types import SimpleNamespace
from argus.models import Asset, Source, Item, Claim, ClaimAudit
from argus.collectors.rss import collect_rss

def _fake_feed():
    e = SimpleNamespace(id="e1", title="Going long BTC target 100k",
                        summary="bullish", link="http://x/1",
                        published_parsed=(2026, 6, 1, 0, 0, 0, 0, 0, 0))
    return SimpleNamespace(entries=[e])

def test_collect_creates_item_claim_audit(session):
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    src = Source(kind="rss", handle="http://feed", display_name="F")
    session.add(src); session.commit()
    with patch("argus.collectors.rss.feedparser.parse", return_value=_fake_feed()), \
         patch("argus.collectors.rss.get_spot_price", return_value=67000.0):
        n = collect_rss(session, src)
    assert n == 1
    assert session.query(Item).count() == 1
    c = session.query(Claim).one()
    assert c.asset == "BTC" and c.direction == "bull" and c.entry_price == 67000.0
    assert session.query(ClaimAudit).one().parser_version == "rule-v1"

def test_collect_dedup(session):
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    src = Source(kind="rss", handle="http://feed", display_name="F")
    session.add(src); session.commit()
    with patch("argus.collectors.rss.feedparser.parse", return_value=_fake_feed()), \
         patch("argus.collectors.rss.get_spot_price", return_value=67000.0):
        collect_rss(session, src)
        collect_rss(session, src)  # ten sam external_id
    assert session.query(Item).count() == 1

def test_price_failure_skips_claim_keeps_item(session):
    from argus.models import Asset, Source, Item, Claim
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BADSYM", scorable=True))
    src = Source(kind="rss", handle="http://feed2", display_name="F2")
    session.add(src); session.commit()
    with patch("argus.collectors.rss.feedparser.parse", return_value=_fake_feed()), \
         patch("argus.collectors.rss.get_spot_price", side_effect=RuntimeError("Invalid symbol")):
        n = collect_rss(session, src)   # must NOT raise
    assert n == 1
    assert session.query(Item).count() == 1   # item kept
    assert session.query(Claim).count() == 0   # claim skipped

def test_collect_emits_sector_claim(session):
    from types import SimpleNamespace
    from unittest.mock import patch
    from argus.models import Asset, Source, Claim
    session.add(Asset(symbol="NFE", kind="stock", yf_symbol="NFE", scorable=True))
    src = Source(kind="news", handle="http://feed-news", display_name="WSJ Markets")
    session.add(src); session.commit()
    entry = SimpleNamespace(id="n1", title="Natural gas prices look bullish", summary="",
                            link="http://x/n1", published_parsed=(2026, 6, 4, 0, 0, 0, 0, 0, 0))
    feed = SimpleNamespace(entries=[entry])
    smap = {"natural_gas": {"aliases": ["natural gas"], "tickers": ["NFE"], "confidence": 0.3}}
    with patch("argus.collectors.rss.feedparser.parse", return_value=feed), \
         patch("argus.collectors.rss.load_sector_map", return_value=smap), \
         patch("argus.collectors.rss.get_spot_price", return_value=25.0):
        collect_rss(session, src)
    c = session.query(Claim).filter_by(asset="NFE").one()
    assert c.direction == "bull" and c.confidence == 0.3
