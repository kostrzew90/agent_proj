from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import select

from argus.models import Asset, Claim, ClaimAudit, Item, LlmCache, LlmQueue, Source
from argus.llm.batch import enqueue_for_llm, process_llm_batch
from argus.llm.extractor import LlmClaim


# ---------------------------------------------------------------------------
# Task 1 — model smoke test
# ---------------------------------------------------------------------------

def test_llm_queue_model_exists(session):
    now = datetime.now(timezone.utc)
    entry = LlmQueue(
        item_id=1,
        text_hash="abc123",
        source_kind="reddit",
        status="pending",
        attempts=0,
        enqueued_at=now,
    )
    session.add(entry)
    session.commit()
    row = session.query(LlmQueue).one()
    assert row.text_hash == "abc123"
    assert row.source_kind == "reddit"
    assert row.status == "pending"
    assert row.attempts == 0
    assert row.processed_at is None
    assert row.last_error is None


# ---------------------------------------------------------------------------
# Task 2 — enqueue_for_llm
# ---------------------------------------------------------------------------

def _src(session, kind="reddit"):
    src = Source(kind=kind, handle=f"http://{kind}", display_name=kind, active=True)
    session.add(src)
    session.commit()
    return src


def _item(session, source, ext="e1"):
    item = Item(source_id=source.id, external_id=ext, text="some text about BTC",
                fetched_at=datetime.now(timezone.utc))
    session.add(item)
    session.commit()
    return item


def test_enqueue_returns_true_first_time(session):
    src = _src(session)
    item = _item(session, src)
    result = enqueue_for_llm(session, item, "reddit", "some text about BTC")
    assert result is True
    assert session.query(LlmQueue).count() == 1


def test_enqueue_dedup_returns_false(session):
    src = _src(session)
    item = _item(session, src)
    enqueue_for_llm(session, item, "reddit", "some text about BTC")
    result = enqueue_for_llm(session, item, "reddit", "some text about BTC")
    assert result is False
    assert session.query(LlmQueue).count() == 1


def test_enqueue_stores_source_kind_and_hash(session):
    src = _src(session, "news")
    item = _item(session, src)
    enqueue_for_llm(session, item, "news", "market text")
    entry = session.query(LlmQueue).one()
    assert entry.source_kind == "news"
    assert entry.status == "pending"
    assert entry.attempts == 0
    assert len(entry.text_hash) == 64  # sha256 hex


# ---------------------------------------------------------------------------
# Task 3 — process_llm_batch: cache hit path
# ---------------------------------------------------------------------------

def _setup_cache_hit(session):
    asset = Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True)
    session.add(asset)
    src = Source(kind="reddit", handle="http://r/crypto", display_name="r/crypto", active=True)
    session.add(src)
    session.flush()
    pub_ts = datetime(2026, 6, 17, 10, 0, tzinfo=timezone.utc)
    item = Item(source_id=src.id, external_id="c1", text="BTC to the moon",
                published_at=pub_ts, fetched_at=datetime.now(timezone.utc))
    session.add(item)
    session.flush()
    h = "deadbeef" * 8  # 64-char fake hash
    entry = LlmQueue(item_id=item.id, text_hash=h, source_kind="reddit",
                     status="pending", attempts=0, enqueued_at=datetime.now(timezone.utc))
    session.add(entry)
    session.add(LlmCache(text_hash=h,
                         result_json=[{"asset": "BTC", "direction": "bull", "reasoning": "moon"}],
                         created_at=datetime.now(timezone.utc)))
    session.commit()
    return asset, pub_ts


def test_cache_hit_creates_claim_without_llm_call(session):
    asset, pub_ts = _setup_cache_hit(session)
    with patch("argus.llm.batch.extract_claims_llm") as mock_llm, \
         patch("argus.llm.batch.get_historical_price", return_value=50000.0):
        stats = process_llm_batch(session, 8, [asset], {})
    assert not mock_llm.called
    assert stats["cache_hits"] == 1
    assert stats["claims"] == 1
    assert stats["processed"] == 1


def test_cache_hit_claim_values(session):
    asset, pub_ts = _setup_cache_hit(session)
    with patch("argus.llm.batch.extract_claims_llm"), \
         patch("argus.llm.batch.get_historical_price", return_value=50000.0):
        process_llm_batch(session, 8, [asset], {})
    claim = session.query(Claim).one()
    assert claim.asset == "BTC"
    assert claim.direction == "bull"
    assert claim.method == "llm"
    assert claim.entry_price == 50000.0
    assert claim.entry_ts == pub_ts
    assert session.query(ClaimAudit).count() == 1


def test_cache_hit_marks_entry_done(session):
    asset, _ = _setup_cache_hit(session)
    with patch("argus.llm.batch.extract_claims_llm"), \
         patch("argus.llm.batch.get_historical_price", return_value=50000.0):
        process_llm_batch(session, 8, [asset], {})
    entry = session.query(LlmQueue).one()
    assert entry.status == "done"
    assert entry.processed_at is not None


# ---------------------------------------------------------------------------
# Task 4 — process_llm_batch: LLM call + historical entry_price
# ---------------------------------------------------------------------------

def test_llm_called_on_cache_miss(session):
    asset = Asset(symbol="ETH", kind="crypto", binance_symbol="ETHUSDT", scorable=True)
    session.add(asset)
    src = Source(kind="reddit", handle="http://r/eth", display_name="r/eth", active=True)
    session.add(src)
    session.flush()
    pub_ts = datetime(2026, 6, 17, 8, 0, tzinfo=timezone.utc)
    item = Item(source_id=src.id, external_id="llm1", text="ETH going up",
                published_at=pub_ts, fetched_at=datetime.now(timezone.utc))
    session.add(item)
    session.flush()
    entry = LlmQueue(item_id=item.id, text_hash="miss" * 16, source_kind="reddit",
                     status="pending", attempts=0, enqueued_at=datetime.now(timezone.utc))
    session.add(entry)
    session.commit()

    fake_claim = LlmClaim("ETH", "bull", 0.35, "going up")
    with patch("argus.llm.batch.extract_claims_llm", return_value=[fake_claim]) as mock_llm, \
         patch("argus.llm.batch.get_historical_price", return_value=3000.0) as mock_price:
        stats = process_llm_batch(session, 8, [asset], {})

    assert mock_llm.called
    assert stats["llm_calls"] == 1
    assert stats["claims"] == 1
    mock_price.assert_called_once_with(asset, pub_ts)
    claim = session.query(Claim).one()
    assert claim.entry_price == 3000.0
    assert claim.entry_ts == pub_ts


def test_llm_result_cached(session):
    asset = Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True)
    session.add(asset)
    src = Source(kind="news", handle="http://news", display_name="news", active=True)
    session.add(src)
    session.flush()
    item = Item(source_id=src.id, external_id="llm2", text="BTC ETF approved",
                fetched_at=datetime.now(timezone.utc))
    session.add(item)
    session.flush()
    h = "cache" * 12 + "1234"  # 64 chars
    entry = LlmQueue(item_id=item.id, text_hash=h, source_kind="news",
                     status="pending", attempts=0, enqueued_at=datetime.now(timezone.utc))
    session.add(entry)
    session.commit()

    with patch("argus.llm.batch.extract_claims_llm",
               return_value=[LlmClaim("BTC", "bull", 0.35, "ETF")]), \
         patch("argus.llm.batch.get_historical_price", return_value=65000.0):
        process_llm_batch(session, 8, [asset], {})

    assert session.query(LlmCache).count() == 1


def test_entry_price_fallback_when_published_at_none(session):
    asset = Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True)
    session.add(asset)
    src = Source(kind="news", handle="http://news2", display_name="news2", active=True)
    session.add(src)
    session.flush()
    item = Item(source_id=src.id, external_id="llm3", text="BTC surge",
                published_at=None, fetched_at=datetime.now(timezone.utc))
    session.add(item)
    session.flush()
    entry = LlmQueue(item_id=item.id, text_hash="fall" * 16, source_kind="news",
                     status="pending", attempts=0, enqueued_at=datetime.now(timezone.utc))
    session.add(entry)
    session.commit()

    with patch("argus.llm.batch.extract_claims_llm",
               return_value=[LlmClaim("BTC", "bull", 0.35, "surge")]), \
         patch("argus.llm.batch.get_historical_price", side_effect=Exception("no data")), \
         patch("argus.llm.batch.get_spot_price", return_value=65000.0) as mock_spot:
        stats = process_llm_batch(session, 8, [asset], {})

    assert mock_spot.called
    assert session.query(Claim).one().entry_price == 65000.0


# ---------------------------------------------------------------------------
# Task 5 — process_llm_batch: error handling
# ---------------------------------------------------------------------------

def _item_in_queue(session, ext, source_kind="reddit", attempts=0):
    src = session.scalar(select(Source).where(Source.kind == source_kind))
    if src is None:
        src = Source(kind=source_kind, handle=f"http://{source_kind}{ext}",
                     display_name=source_kind, active=True)
        session.add(src)
        session.flush()
    item = Item(source_id=src.id, external_id=ext, text="text",
                fetched_at=datetime.now(timezone.utc))
    session.add(item)
    session.flush()
    entry = LlmQueue(item_id=item.id, text_hash=f"err{ext}" + "x" * 60,
                     source_kind=source_kind, status="pending",
                     attempts=attempts, enqueued_at=datetime.now(timezone.utc))
    session.add(entry)
    session.commit()
    return entry


def test_llm_error_increments_attempts(session):
    asset = Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True)
    session.add(asset)
    session.commit()
    _item_in_queue(session, "err1")
    with patch("argus.llm.batch.extract_claims_llm", side_effect=RuntimeError("503")):
        stats = process_llm_batch(session, 8, [asset], {})
    assert stats["errors"] == 1
    assert stats["claims"] == 0
    entry = session.query(LlmQueue).one()
    assert entry.attempts == 1
    assert entry.status == "pending"
    assert "503" in entry.last_error


def test_max_attempts_marks_failed(session):
    asset = Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True)
    session.add(asset)
    session.commit()
    _item_in_queue(session, "err2", attempts=4)  # _MAX_ATTEMPTS - 1
    with patch("argus.llm.batch.extract_claims_llm", side_effect=RuntimeError("boom")):
        process_llm_batch(session, 8, [asset], {})
    entry = session.query(LlmQueue).one()
    assert entry.status == "failed"
    assert entry.attempts == 5


def test_exhausted_items_skipped_in_next_batch(session):
    asset = Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True)
    session.add(asset)
    session.commit()
    _item_in_queue(session, "err3", attempts=5)  # already at max
    with patch("argus.llm.batch.extract_claims_llm") as mock_llm:
        stats = process_llm_batch(session, 8, [asset], {})
    assert not mock_llm.called
    assert stats["processed"] == 0


# ---------------------------------------------------------------------------
# Task 6 — process_llm_batch: priority ordering
# ---------------------------------------------------------------------------

def test_reddit_processed_before_news(session):
    asset = Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True)
    session.add(asset)
    session.flush()
    src_r = Source(kind="reddit", handle="http://r/r", display_name="reddit", active=True)
    src_n = Source(kind="news", handle="http://news/n", display_name="news", active=True)
    session.add(src_r)
    session.add(src_n)
    session.flush()
    now = datetime.now(timezone.utc)

    # News enqueued FIRST (older timestamp) — should still be processed AFTER reddit
    item_n = Item(source_id=src_n.id, external_id="pn1", text="news text",
                  fetched_at=now)
    session.add(item_n)
    session.flush()
    entry_n = LlmQueue(item_id=item_n.id, text_hash="hnews" + "x" * 59,
                       source_kind="news", status="pending", attempts=0,
                       enqueued_at=now)
    session.add(entry_n)

    item_r = Item(source_id=src_r.id, external_id="pr1", text="reddit text",
                  fetched_at=now)
    session.add(item_r)
    session.flush()
    entry_r = LlmQueue(item_id=item_r.id, text_hash="hredd" + "x" * 59,
                       source_kind="reddit", status="pending", attempts=0,
                       enqueued_at=now)
    session.add(entry_r)
    session.commit()

    processed_texts = []

    def fake_llm(text, *a, **kw):
        processed_texts.append(text)
        return []

    # batch_size=1 — only first item processed
    with patch("argus.llm.batch.extract_claims_llm", side_effect=fake_llm):
        process_llm_batch(session, 1, [asset], {})

    assert processed_texts == ["reddit text"]
