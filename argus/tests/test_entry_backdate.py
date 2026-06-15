"""TDD: entry_price/entry_ts must be backdated to signal moment, not detection time."""
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, call
import pytest

from argus.collectors.insider import InsiderTransaction, collect_insider
from argus.collectors.edgar import InsiderTransaction as EdgarTx, collect_edgar_insider


TX_DATE = datetime(2024, 10, 1, tzinfo=timezone.utc)
HIST_PRICE = 8.63
SPOT_PRICE  = 10.0   # different — proves we're NOT using spot

def _sample_insider_tx(total=50_000_000.0):
    return InsiderTransaction(
        date=TX_DATE, insider_name="Wesley Edens", role="CEO",
        transaction_type="Buy", shares=5_793_742,
        price=8.63, total_value=total, external_id="abc"
    )

def _make_session():
    s = MagicMock()
    s.scalar.return_value = None   # no existing item
    s.flush = MagicMock()
    s.commit = MagicMock()
    return s

def _make_asset(sym="NFE"):
    a = MagicMock(); a.symbol = sym; a.kind = "stock"; return a

def _make_source(sid=99):
    src = MagicMock(); src.id = sid; return src


# ── insider.py (MarketBeat) ───────────────────────────────────────────────────

def test_insider_entry_ts_is_transaction_date():
    """entry_ts must equal tx.date, not time of collection."""
    session = _make_session()
    with patch("argus.collectors.insider.scrape_insider_trades",
               return_value=[_sample_insider_tx()]), \
         patch("argus.collectors.insider.get_historical_price",
               return_value=HIST_PRICE) as mock_hist, \
         patch("argus.collectors.insider.get_spot_price",
               return_value=SPOT_PRICE) as mock_spot:
        collect_insider(session, _make_source(), "NFE", _make_asset())

    mock_spot.assert_not_called()
    mock_hist.assert_called_once()
    # verify entry_ts on the Claim add call
    claim_add_calls = [c for c in session.add.call_args_list
                       if hasattr(c.args[0], 'entry_ts')]
    assert any(c.args[0].entry_ts == TX_DATE for c in claim_add_calls)


def test_insider_entry_price_is_historical():
    session = _make_session()
    with patch("argus.collectors.insider.scrape_insider_trades",
               return_value=[_sample_insider_tx()]), \
         patch("argus.collectors.insider.get_historical_price",
               return_value=HIST_PRICE):
        collect_insider(session, _make_source(), "NFE", _make_asset())

    claim_add_calls = [c for c in session.add.call_args_list
                       if hasattr(c.args[0], 'entry_price')]
    assert any(c.args[0].entry_price == HIST_PRICE for c in claim_add_calls)


def test_insider_falls_back_to_spot_when_historical_fails():
    session = _make_session()
    with patch("argus.collectors.insider.scrape_insider_trades",
               return_value=[_sample_insider_tx()]), \
         patch("argus.collectors.insider.get_historical_price",
               side_effect=Exception("no data")), \
         patch("argus.collectors.insider.get_spot_price",
               return_value=SPOT_PRICE):
        n = collect_insider(session, _make_source(), "NFE", _make_asset())
    assert n == 1   # claim still created via fallback


# ── edgar.py ──────────────────────────────────────────────────────────────────

def _edgar_tx(total=49_999_993.0):
    from argus.collectors.edgar import InsiderTransaction as ET
    return ET(date=TX_DATE, insider_name="EDENS WESLEY R", role="CEO",
              transaction_type="Purchase", shares=5_793_742,
              price=8.63, total_value=total, external_id="edgar_abc")

def test_edgar_entry_ts_is_transaction_date():
    session = _make_session()
    with patch("argus.collectors.edgar._fetch_submissions",
               return_value=[{"filing_date": "2024-10-03",
                              "accession": "0001749723-24-000096",
                              "primary_doc": "form4.xml", "cik": 1749723}]), \
         patch("argus.collectors.edgar._fetch_form4_xml", return_value="<x/>"), \
         patch("argus.collectors.edgar.parse_form4_xml", return_value=[_edgar_tx()]), \
         patch("argus.collectors.edgar.get_historical_price",
               return_value=HIST_PRICE) as mock_hist, \
         patch("argus.collectors.edgar.get_spot_price",
               return_value=SPOT_PRICE) as mock_spot:
        collect_edgar_insider(session, _make_source(), "NFE", 1749723, _make_asset())

    mock_spot.assert_not_called()
    claim_adds = [c for c in session.add.call_args_list
                  if hasattr(c.args[0], 'entry_ts')]
    assert any(c.args[0].entry_ts == TX_DATE for c in claim_adds)


def test_edgar_entry_price_is_historical():
    session = _make_session()
    with patch("argus.collectors.edgar._fetch_submissions",
               return_value=[{"filing_date": "2024-10-03",
                              "accession": "0001749723-24-000096",
                              "primary_doc": "form4.xml", "cik": 1749723}]), \
         patch("argus.collectors.edgar._fetch_form4_xml", return_value="<x/>"), \
         patch("argus.collectors.edgar.parse_form4_xml", return_value=[_edgar_tx()]), \
         patch("argus.collectors.edgar.get_historical_price", return_value=HIST_PRICE):
        collect_edgar_insider(session, _make_source(), "NFE", 1749723, _make_asset())

    claim_adds = [c for c in session.add.call_args_list
                  if hasattr(c.args[0], 'entry_price')]
    assert any(c.args[0].entry_price == HIST_PRICE for c in claim_adds)


def test_edgar_falls_back_to_spot():
    session = _make_session()
    with patch("argus.collectors.edgar._fetch_submissions",
               return_value=[{"filing_date": "2024-10-03",
                              "accession": "0001749723-24-000096",
                              "primary_doc": "form4.xml", "cik": 1749723}]), \
         patch("argus.collectors.edgar._fetch_form4_xml", return_value="<x/>"), \
         patch("argus.collectors.edgar.parse_form4_xml", return_value=[_edgar_tx()]), \
         patch("argus.collectors.edgar.get_historical_price",
               side_effect=Exception("too old")), \
         patch("argus.collectors.edgar.get_spot_price", return_value=SPOT_PRICE):
        n = collect_edgar_insider(session, _make_source(), "NFE", 1749723, _make_asset())
    assert n == 1
