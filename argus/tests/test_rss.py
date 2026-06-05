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
    assert session.query(ClaimAudit).one().parser_version == "rule-v2"

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

def test_gap_fill_calls_llm_when_rule_empty(session):
    from types import SimpleNamespace
    from unittest.mock import patch
    from argus.models import Asset, Source, Claim
    from argus.llm.extractor import LlmClaim
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    src = Source(kind="news", handle="http://f", display_name="WSJ Markets"); session.add(src); session.commit()
    entry = SimpleNamespace(id="g1", title="Fed signals dovish pivot", summary="",
                            link="http://x/g1", published_parsed=(2026, 6, 5, 0, 0, 0, 0, 0, 0))
    feed = SimpleNamespace(entries=[entry])
    with patch("argus.collectors.rss.feedparser.parse", return_value=feed), \
         patch("argus.collectors.rss.load_sector_map", return_value={}), \
         patch("argus.collectors.rss.get_spot_price", return_value=67000.0), \
         patch("argus.collectors.rss.extract_claims_llm",
               return_value=[LlmClaim("BTC", "bull", 0.35, "dovish -> risk on")]) as mllm:
        collect_rss(session, src)
    assert mllm.called
    c = session.query(Claim).filter_by(asset="BTC").one()
    assert c.method == "llm" and c.confidence == 0.35

def test_no_gap_fill_when_rule_found_claim(session):
    from types import SimpleNamespace
    from unittest.mock import patch
    from argus.models import Asset, Source
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    src = Source(kind="reddit", handle="http://f2", display_name="r/x"); session.add(src); session.commit()
    entry = SimpleNamespace(id="g2", title="long BTC", summary="", link="http://x/g2",
                            published_parsed=(2026, 6, 5, 0, 0, 0, 0, 0, 0))
    feed = SimpleNamespace(entries=[entry])
    with patch("argus.collectors.rss.feedparser.parse", return_value=feed), \
         patch("argus.collectors.rss.load_sector_map", return_value={}), \
         patch("argus.collectors.rss.get_spot_price", return_value=67000.0), \
         patch("argus.collectors.rss.extract_claims_llm") as mllm:
        collect_rss(session, src)
    assert not mllm.called

def test_gap_fill_uses_cache_on_second_run(session):
    from types import SimpleNamespace
    from unittest.mock import patch
    from argus.models import Asset, Source
    from argus.llm.extractor import LlmClaim
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    s1 = Source(kind="news", handle="http://fa", display_name="WSJ"); session.add(s1)
    s2 = Source(kind="news", handle="http://fb", display_name="MW"); session.add(s2); session.commit()
    def feed_for(_handle):
        e = SimpleNamespace(id=None, title="Fed dovish pivot ahead", summary="",
                            link="http://x/same", published_parsed=(2026,6,5,0,0,0,0,0,0))
        return SimpleNamespace(entries=[e])
    with patch("argus.collectors.rss.feedparser.parse", side_effect=lambda h: feed_for(h)), \
         patch("argus.collectors.rss.load_sector_map", return_value={}), \
         patch("argus.collectors.rss.get_spot_price", return_value=67000.0), \
         patch("argus.collectors.rss.extract_claims_llm",
               return_value=[LlmClaim("BTC","bull",0.35,"r")]) as mllm:
        collect_rss(session, s1)
        collect_rss(session, s2)
    assert mllm.call_count == 1
