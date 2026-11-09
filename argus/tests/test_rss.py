from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
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

def test_collect_rss_no_inline_llm(session):
    """collect_rss enqueues for batch, never calls extract_claims_llm inline."""
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    source = Source(handle="http://example.com/rss", kind="reddit", display_name="test", active=True)
    session.add(source); session.commit()
    entry = SimpleNamespace(
        id="z1", title="Fed signals dovish pivot for BTC", summary="",
        link="http://x/z1", published_parsed=(2026, 6, 5, 0, 0, 0, 0, 0, 0)
    )
    with patch("argus.collectors.rss.enqueue_for_llm") as mock_enq, \
         patch("feedparser.parse", return_value=SimpleNamespace(entries=[entry])), \
         patch("argus.collectors.rss.load_sector_map", return_value={}):
        collect_rss(session, source)
    mock_enq.assert_called_once()

def test_gap_fill_enqueues_when_rule_empty(session):
    """When rule parser finds no claims and source is reddit/news, item is enqueued
    (given the item mentions a watchlist asset, otherwise the pre-filter skips it)."""
    from argus.models import LlmQueue
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    src = Source(kind="reddit", handle="http://f", display_name="r/crypto"); session.add(src); session.commit()
    entry = SimpleNamespace(id="g1", title="Fed signals dovish pivot for BTC", summary="",
                            link="http://x/g1", published_parsed=(2026, 6, 5, 0, 0, 0, 0, 0, 0))
    feed = SimpleNamespace(entries=[entry])
    with patch("argus.collectors.rss.feedparser.parse", return_value=feed), \
         patch("argus.collectors.rss.load_sector_map", return_value={}):
        collect_rss(session, src)
    assert session.query(LlmQueue).count() == 1
    assert session.query(LlmQueue).one().source_kind == "reddit"

def test_no_enqueue_when_rule_found_claim(session):
    """When rule parser finds claims, no enqueue happens."""
    from argus.models import LlmQueue
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    src = Source(kind="reddit", handle="http://f2", display_name="r/x"); session.add(src); session.commit()
    entry = SimpleNamespace(id="g2", title="long BTC", summary="", link="http://x/g2",
                            published_parsed=(2026, 6, 5, 0, 0, 0, 0, 0, 0))
    feed = SimpleNamespace(entries=[entry])
    with patch("argus.collectors.rss.feedparser.parse", return_value=feed), \
         patch("argus.collectors.rss.load_sector_map", return_value={}), \
         patch("argus.collectors.rss.get_spot_price", return_value=67000.0):
        collect_rss(session, src)
    assert session.query(LlmQueue).count() == 0

def test_non_reddit_news_source_not_enqueued(session):
    """Sources with kind other than reddit/news are not enqueued for LLM."""
    from argus.models import LlmQueue
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    src = Source(kind="rss", handle="http://other", display_name="other"); session.add(src); session.commit()
    entry = SimpleNamespace(id="o1", title="Fed signals dovish pivot", summary="",
                            link="http://x/o1", published_parsed=(2026, 6, 5, 0, 0, 0, 0, 0, 0))
    feed = SimpleNamespace(entries=[entry])
    with patch("argus.collectors.rss.feedparser.parse", return_value=feed), \
         patch("argus.collectors.rss.load_sector_map", return_value={}):
        collect_rss(session, src)
    assert session.query(LlmQueue).count() == 0


# --- pre-filter: only enqueue items that mention a watchlist asset/alias ---

def test_prefilter_reddit_symbol_mention_enqueued(session):
    """Reddit item mentioning a watchlist symbol as a standalone word passes the pre-filter."""
    from argus.models import LlmQueue
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    src = Source(kind="reddit", handle="http://pf1", display_name="r/pf1"); session.add(src); session.commit()
    entry = SimpleNamespace(id="pf1", title="BTC network activity update", summary="",
                            link="http://x/pf1", published_parsed=(2026, 6, 5, 0, 0, 0, 0, 0, 0))
    feed = SimpleNamespace(entries=[entry])
    with patch("argus.collectors.rss.feedparser.parse", return_value=feed), \
         patch("argus.collectors.rss.load_sector_map", return_value={}):
        collect_rss(session, src)
    assert session.query(LlmQueue).count() == 1


def test_prefilter_reddit_cashtag_enqueued(session):
    """Reddit item mentioning a watchlist symbol as a $CASHTAG passes the pre-filter."""
    from argus.models import LlmQueue
    session.add(Asset(symbol="ETH", kind="crypto", binance_symbol="ETHUSDT", scorable=True))
    src = Source(kind="reddit", handle="http://pf2", display_name="r/pf2"); session.add(src); session.commit()
    entry = SimpleNamespace(id="pf2", title="Watch $ETH before the close", summary="",
                            link="http://x/pf2", published_parsed=(2026, 6, 5, 0, 0, 0, 0, 0, 0))
    feed = SimpleNamespace(entries=[entry])
    with patch("argus.collectors.rss.feedparser.parse", return_value=feed), \
         patch("argus.collectors.rss.load_sector_map", return_value={}):
        collect_rss(session, src)
    assert session.query(LlmQueue).count() == 1


def test_prefilter_news_sector_alias_enqueued(session):
    """News item mentioning a sector alias (no direct symbol) passes the pre-filter."""
    from argus.models import LlmQueue
    session.add(Asset(symbol="XOMA", kind="stock", yf_symbol="XOMA", scorable=True))
    src = Source(kind="news", handle="http://pf3", display_name="Newswire"); session.add(src); session.commit()
    entry = SimpleNamespace(id="pf3", title="New biotech breakthrough in gene therapy", summary="",
                            link="http://x/pf3", published_parsed=(2026, 6, 5, 0, 0, 0, 0, 0, 0))
    feed = SimpleNamespace(entries=[entry])
    smap = {"biotech": {"aliases": ["biotech", "fda approval"], "tickers": ["XOMA"], "confidence": 0.3}}
    with patch("argus.collectors.rss.feedparser.parse", return_value=feed), \
         patch("argus.collectors.rss.load_sector_map", return_value=smap):
        collect_rss(session, src)
    assert session.query(LlmQueue).count() == 1


def test_prefilter_generic_item_skipped(session):
    """Item with no watchlist/sector mention is not enqueued and enqueue_skipped is counted."""
    from argus.models import LlmQueue
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    src = Source(kind="reddit", handle="http://pf4", display_name="r/pf4"); session.add(src); session.commit()
    entry = SimpleNamespace(id="pf4", title="Local weather turns colder this weekend", summary="",
                            link="http://x/pf4", published_parsed=(2026, 6, 5, 0, 0, 0, 0, 0, 0))
    feed = SimpleNamespace(entries=[entry])
    with patch("argus.collectors.rss.feedparser.parse", return_value=feed), \
         patch("argus.collectors.rss.load_sector_map", return_value={}), \
         patch("argus.collectors.rss.logger") as mock_logger:
        collect_rss(session, src)
    assert session.query(LlmQueue).count() == 0
    logged_stats = mock_logger.info.call_args.args[-1]
    assert logged_stats["enqueue_skipped"] == 1
    assert logged_stats["enqueued"] == 0


def test_prefilter_case_insensitive_match(session):
    """Lowercase mention mid-sentence still matches the watchlist symbol."""
    from argus.models import LlmQueue
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    src = Source(kind="reddit", handle="http://pf5", display_name="r/pf5"); session.add(src); session.commit()
    entry = SimpleNamespace(id="pf5", title="Some folks think btc is going nowhere today", summary="",
                            link="http://x/pf5", published_parsed=(2026, 6, 5, 0, 0, 0, 0, 0, 0))
    feed = SimpleNamespace(entries=[entry])
    with patch("argus.collectors.rss.feedparser.parse", return_value=feed), \
         patch("argus.collectors.rss.load_sector_map", return_value={}):
        collect_rss(session, src)
    assert session.query(LlmQueue).count() == 1


def test_prefilter_no_substring_false_positive(session):
    """A word containing the symbol as a substring ('solid' vs SOL) must not match."""
    from argus.models import LlmQueue
    session.add(Asset(symbol="SOL", kind="crypto", binance_symbol="SOLUSDT", scorable=True))
    src = Source(kind="reddit", handle="http://pf6", display_name="r/pf6"); session.add(src); session.commit()
    entry = SimpleNamespace(id="pf6", title="This proposal seems solid to most of us", summary="",
                            link="http://x/pf6", published_parsed=(2026, 6, 5, 0, 0, 0, 0, 0, 0))
    feed = SimpleNamespace(entries=[entry])
    with patch("argus.collectors.rss.feedparser.parse", return_value=feed), \
         patch("argus.collectors.rss.load_sector_map", return_value={}):
        collect_rss(session, src)
    assert session.query(LlmQueue).count() == 0


def test_reddit_source_uses_custom_agent(session):
    from argus.collectors.rss import _REDDIT_UA
    src = Source(kind="reddit", handle="http://reddit/r/x/.rss", display_name="r/x")
    session.add(src); session.commit()
    with patch("argus.collectors.rss.feedparser.parse", return_value=SimpleNamespace(entries=[])) as p:
        collect_rss(session, src)
    p.assert_called_once_with("http://reddit/r/x/.rss", agent=_REDDIT_UA)


def test_news_source_has_no_agent(session):
    src = Source(kind="news", handle="http://news/feed", display_name="N")
    session.add(src); session.commit()
    with patch("argus.collectors.rss.feedparser.parse", return_value=SimpleNamespace(entries=[])) as p:
        collect_rss(session, src)
    p.assert_called_once_with("http://news/feed")


def test_http_error_status_is_logged(session, caplog):
    import logging
    src = Source(kind="reddit", handle="http://reddit/r/y/.rss", display_name="r/y")
    session.add(src); session.commit()
    with caplog.at_level(logging.WARNING), \
         patch("argus.collectors.rss.feedparser.parse",
               return_value=SimpleNamespace(entries=[], status=429)):
        assert collect_rss(session, src) == 0
    assert "HTTP 429" in caplog.text


def test_rss_job_reddit_last_with_delays(session, monkeypatch):
    import argus.main as m
    session.add_all([
        Source(kind="reddit", handle="h1", display_name="r1"),
        Source(kind="news", handle="h2", display_name="n1"),
        Source(kind="reddit", handle="h3", display_name="r2"),
        Source(kind="rss", handle="h4", display_name="f1"),
        Source(kind="reddit", handle="h5", display_name="r3"),
    ])
    session.commit()

    class _Ctx:
        def __enter__(self): return session
        def __exit__(self, *a): return False

    order, sleeps = [], []
    monkeypatch.setattr(m, "SessionLocal", lambda: _Ctx())
    monkeypatch.setattr(m, "collect_rss", lambda s, src: order.append(src.kind))
    monkeypatch.setattr(m.time, "sleep", lambda d: sleeps.append(d))
    monkeypatch.setenv("ARGUS_REDDIT_DELAY_S", "7")
    m._rss_job()
    assert order == ["news", "rss", "reddit", "reddit", "reddit"]
    assert sleeps == [7.0, 7.0]
