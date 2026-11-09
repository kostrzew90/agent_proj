"""TDD tests for MarketBeat insider collector."""
import hashlib
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
import pytest

from argus.collectors.insider import (
    InsiderTransaction,
    _parse_value,
    _parse_shares,
    _confidence,
    _make_ext_id,
    parse_insider_table,
    collect_insider,
    _EXCHANGE,
)


# ── unit: parsers ────────────────────────────────────────────────────────────

def test_parse_value_full():
    assert _parse_value("$2,505,000.00") == pytest.approx(2_505_000.0)

def test_parse_value_million():
    assert _parse_value("$35.54 million") == pytest.approx(35_540_000.0)

def test_parse_value_billion():
    assert _parse_value("$1.2 billion") == pytest.approx(1_200_000_000.0)

def test_parse_value_empty():
    assert _parse_value("") == 0.0

def test_parse_shares_plain():
    assert _parse_shares("100,000") == 100_000

def test_parse_shares_with_label():
    assert _parse_shares("852,051 shares") == 852_051

def test_confidence_tiers():
    assert _confidence(5_000) == 0.45          # below threshold
    assert _confidence(100_000) == 0.50
    assert _confidence(1_000_000) == 0.55
    assert _confidence(10_000_000) == 0.60
    assert _confidence(100_000_000) == 0.65

def test_make_ext_id_deterministic():
    a = _make_ext_id("XOMA", "20251204", "Owen Hughes", 100000, "Buy")
    b = _make_ext_id("XOMA", "20251204", "Owen Hughes", 100000, "Buy")
    assert a == b

def test_make_ext_id_differs_on_type():
    a = _make_ext_id("XOMA", "20251204", "Owen Hughes", 100000, "Buy")
    b = _make_ext_id("XOMA", "20251204", "Owen Hughes", 100000, "Sale")
    assert a != b


# ── unit: HTML parser ─────────────────────────────────────────────────────────

_INSIDER_HTML = """
<table class="scroll-table sort-table">
  <thead><tr>
    <th>Transaction Date</th><th>Insider</th><th>Buy/Sell</th>
    <th>Number of Shares</th><th>Average Share Price</th>
    <th>Total Transaction</th><th>Details</th>
  </tr></thead>
  <tbody>
    <tr>
      <td data-sort-value="20251204000000">12/4/2025</td>
      <td data-clean="Owen Hughes|CEO">Owen Hughes</td>
      <td>Buy</td>
      <td>100,000</td>
      <td>$25.05</td>
      <td>$2,505,000.00</td>
      <td></td>
    </tr>
    <tr>
      <td data-sort-value="20251101000000">11/1/2025</td>
      <td data-clean="Jane Doe|CFO">Jane Doe</td>
      <td>Sale</td>
      <td>10,000</td>
      <td>$22.00</td>
      <td>$220,000.00</td>
      <td></td>
    </tr>
  </tbody>
</table>
"""

def test_parse_insider_table_returns_all():
    txs = parse_insider_table("XOMA", _INSIDER_HTML)
    assert len(txs) == 2

def test_parse_insider_table_buy_fields():
    txs = parse_insider_table("XOMA", _INSIDER_HTML)
    buy = next(t for t in txs if t.transaction_type == "Buy")
    assert buy.insider_name == "Owen Hughes"
    assert buy.role == "CEO"
    assert buy.shares == 100_000
    assert buy.price == pytest.approx(25.05)
    assert buy.total_value == pytest.approx(2_505_000.0)
    assert buy.date == datetime(2025, 12, 4, tzinfo=timezone.utc)

def test_parse_insider_table_sale_fields():
    txs = parse_insider_table("XOMA", _INSIDER_HTML)
    sale = next(t for t in txs if t.transaction_type == "Sale")
    assert sale.insider_name == "Jane Doe"
    assert sale.total_value == pytest.approx(220_000.0)

def test_parse_insider_table_empty_html():
    assert parse_insider_table("XOMA", "<html></html>") == []

def test_parse_insider_table_bad_row_skipped():
    html = '<table class="scroll-table sort-table"><tbody><tr><td>bad</td></tr></tbody></table>'
    assert parse_insider_table("XOMA", html) == []


# ── integration: collect_insider ─────────────────────────────────────────────

def _make_session(existing_item=False):
    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = MagicMock(return_value=False)
    # scalar: None = no existing item (new transaction)
    session.scalar.return_value = MagicMock() if existing_item else None
    session.flush = MagicMock()
    session.commit = MagicMock()
    return session

def _make_source(sid=99):
    src = MagicMock()
    src.id = sid
    return src

def _make_asset(sym="XOMA"):
    a = MagicMock()
    a.symbol = sym
    return a

def _sample_tx(total=2_505_000.0, tx_type="Buy"):
    return InsiderTransaction(
        date=datetime(2025, 12, 4, tzinfo=timezone.utc),
        insider_name="Owen Hughes", role="CEO",
        transaction_type=tx_type, shares=100_000,
        price=25.05, total_value=total,
        external_id="abc123"
    )


def test_collect_insider_buy_creates_claim():
    session = _make_session()
    with patch("argus.collectors.insider.scrape_insider_trades",
               return_value=[_sample_tx()]), \
         patch("argus.collectors.insider.get_spot_price", return_value=25.0):
        n = collect_insider(session, _make_source(), "XOMA", _make_asset())
    assert n == 1
    session.commit.assert_called_once()


def test_collect_insider_sale_skipped():
    session = _make_session()
    with patch("argus.collectors.insider.scrape_insider_trades",
               return_value=[_sample_tx(tx_type="Sale")]), \
         patch("argus.collectors.insider.get_spot_price", return_value=25.0):
        n = collect_insider(session, _make_source(), "XOMA", _make_asset())
    assert n == 0


def test_collect_insider_tiny_tx_skipped():
    session = _make_session()
    with patch("argus.collectors.insider.scrape_insider_trades",
               return_value=[_sample_tx(total=5_000)]), \
         patch("argus.collectors.insider.get_spot_price", return_value=25.0):
        n = collect_insider(session, _make_source(), "XOMA", _make_asset())
    assert n == 0


def test_collect_insider_dedup():
    session = _make_session(existing_item=True)  # item already in DB
    with patch("argus.collectors.insider.scrape_insider_trades",
               return_value=[_sample_tx()]):
        n = collect_insider(session, _make_source(), "XOMA", _make_asset())
    assert n == 0


def test_collect_insider_scrape_error_returns_zero():
    session = _make_session()
    with patch("argus.collectors.insider.scrape_insider_trades",
               side_effect=Exception("timeout")):
        n = collect_insider(session, _make_source(), "XOMA", _make_asset())
    assert n == 0


def test_collect_insider_price_error_skips_claim():
    session = _make_session()
    with patch("argus.collectors.insider.scrape_insider_trades",
               return_value=[_sample_tx()]), \
         patch("argus.collectors.insider.get_spot_price",
               side_effect=Exception("no price")):
        n = collect_insider(session, _make_source(), "XOMA", _make_asset())
    assert n == 0


def test_exchange_mapping_covers_watchlist():
    for sym in ["XOMA", "LCID", "NFE", "NTR", "DLNG", "PLG", "BYND"]:
        assert sym in _EXCHANGE, f"missing exchange for {sym}"
