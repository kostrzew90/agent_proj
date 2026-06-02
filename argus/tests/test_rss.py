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
