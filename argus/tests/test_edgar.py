"""TDD tests for EDGAR Form 4 insider collector."""
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
import pytest

from argus.collectors.edgar import (
    parse_form4_xml,
    _parse_submissions,
    _make_edgar_ext_id,
    collect_edgar_insider,
)


# ── sample Form 4 XML (minimal but realistic) ────────────────────────────────

_FORM4_PURCHASE = """<?xml version="1.0"?>
<ownershipDocument>
  <issuer>
    <issuerCik>0000754811</issuerCik>
    <issuerName>XOMA ROYALTY CORP</issuerName>
    <issuerTradingSymbol>XOMA</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerName>Owen Hughes</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isOfficer>1</isOfficer>
      <officerTitle>CEO</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2025-12-04</value></transactionDate>
      <transactionCoding>
        <transactionCode>P</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>100000</value></transactionShares>
        <transactionPricePerShare><value>25.05</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""

_FORM4_SALE = """<?xml version="1.0"?>
<ownershipDocument>
  <issuer><issuerTradingSymbol>XOMA</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Jane Doe</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isOfficer>1</isOfficer><officerTitle>CFO</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2025-11-01</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>5000</value></transactionShares>
        <transactionPricePerShare><value>22.00</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""

_FORM4_MULTI = """<?xml version="1.0"?>
<ownershipDocument>
  <issuer><issuerTradingSymbol>NFE</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Wesley R Edens</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isOfficer>1</isOfficer><officerTitle>CEO</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2024-10-15</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>3000000</value></transactionShares>
        <transactionPricePerShare><value>8.63</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionDate><value>2024-10-16</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>2793742</value></transactionShares>
        <transactionPricePerShare><value>8.63</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""

_SUBMISSIONS_JSON = {
    "cik": "754811",
    "name": "XOMA ROYALTY CORP",
    "filings": {
        "recent": {
            "form":            ["4", "10-K", "4", "8-K"],
            "filingDate":      ["2025-12-05", "2025-11-30", "2025-11-02", "2025-10-15"],
            "accessionNumber": ["0000754811-25-000010", "0000754811-25-000009",
                                "0000754811-25-000008", "0000754811-25-000007"],
            "primaryDocument": ["xoma-form4.xml", "xoma-10k.htm",
                                "xoma-form4b.xml", "xoma-8k.htm"],
        }
    }
}


# ── unit: parse_form4_xml ─────────────────────────────────────────────────────

def test_parse_purchase():
    txs = parse_form4_xml(_FORM4_PURCHASE)
    assert len(txs) == 1
    t = txs[0]
    assert t.insider_name == "Owen Hughes"
    assert t.role == "CEO"
    assert t.transaction_type == "Purchase"
    assert t.shares == 100_000
    assert t.price == pytest.approx(25.05)
    assert t.total_value == pytest.approx(2_505_000.0)
    assert t.date == datetime(2025, 12, 4, tzinfo=timezone.utc)

def test_parse_sale_returns_empty():
    txs = parse_form4_xml(_FORM4_SALE)
    assert txs == []  # sales excluded

def test_parse_multi_transactions():
    txs = parse_form4_xml(_FORM4_MULTI)
    assert len(txs) == 2
    assert txs[0].shares == 3_000_000
    assert txs[1].shares == 2_793_742

def test_parse_empty_xml():
    assert parse_form4_xml("<ownershipDocument/>") == []

def test_parse_ext_id_deterministic():
    txs1 = parse_form4_xml(_FORM4_PURCHASE)
    txs2 = parse_form4_xml(_FORM4_PURCHASE)
    assert txs1[0].external_id == txs2[0].external_id

def test_parse_purchase_total_value():
    txs = parse_form4_xml(_FORM4_MULTI)
    assert txs[0].total_value == pytest.approx(3_000_000 * 8.63)


# ── unit: _parse_submissions ──────────────────────────────────────────────────

def test_parse_submissions_returns_form4_only():
    filings = _parse_submissions(_SUBMISSIONS_JSON)
    assert len(filings) == 2
    assert all(f["form"] == "4" for f in filings)

def test_parse_submissions_fields():
    filings = _parse_submissions(_SUBMISSIONS_JSON)
    f = filings[0]
    assert f["filing_date"] == "2025-12-05"
    assert f["accession"] == "0000754811-25-000010"
    assert f["primary_doc"] == "xoma-form4.xml"

def test_parse_submissions_empty():
    assert _parse_submissions({}) == []


# ── unit: ext_id ─────────────────────────────────────────────────────────────

def test_edgar_ext_id_deterministic():
    a = _make_edgar_ext_id("XOMA", "20251204", "Owen Hughes", 100000)
    b = _make_edgar_ext_id("XOMA", "20251204", "Owen Hughes", 100000)
    assert a == b

def test_edgar_ext_id_differs_by_shares():
    a = _make_edgar_ext_id("XOMA", "20251204", "Owen Hughes", 100000)
    b = _make_edgar_ext_id("XOMA", "20251204", "Owen Hughes", 99999)
    assert a != b


# ── integration: collect_edgar_insider ───────────────────────────────────────

def _make_session(existing=False):
    s = MagicMock()
    s.scalar.return_value = MagicMock() if existing else None
    s.flush = MagicMock()
    s.commit = MagicMock()
    return s

def _make_source(sid=10):
    src = MagicMock(); src.id = sid; return src

def _make_asset(sym="XOMA"):
    a = MagicMock(); a.symbol = sym; return a


def test_collect_creates_claim_for_purchase():
    session = _make_session()
    with patch("argus.collectors.edgar._fetch_submissions",
               return_value=[{"filing_date": "2025-12-05",
                              "accession": "0000754811-25-000010",
                              "primary_doc": "f4.xml", "cik": 754811}]), \
         patch("argus.collectors.edgar._fetch_form4_xml",
               return_value=_FORM4_PURCHASE), \
         patch("argus.collectors.edgar.get_spot_price", return_value=41.5):
        n = collect_edgar_insider(session, _make_source(), "XOMA", 754811, _make_asset())
    assert n == 1
    session.commit.assert_called()


def test_collect_dedup_skips_existing():
    session = _make_session(existing=True)
    with patch("argus.collectors.edgar._fetch_submissions",
               return_value=[{"filing_date": "2025-12-05",
                              "accession": "0000754811-25-000010",
                              "primary_doc": "f4.xml", "cik": 754811}]), \
         patch("argus.collectors.edgar._fetch_form4_xml",
               return_value=_FORM4_PURCHASE):
        n = collect_edgar_insider(session, _make_source(), "XOMA", 754811, _make_asset())
    assert n == 0


def test_collect_fetch_error_returns_zero():
    session = _make_session()
    with patch("argus.collectors.edgar._fetch_submissions",
               side_effect=Exception("network")):
        n = collect_edgar_insider(session, _make_source(), "XOMA", 754811, _make_asset())
    assert n == 0


def test_collect_price_error_skips():
    session = _make_session()
    with patch("argus.collectors.edgar._fetch_submissions",
               return_value=[{"filing_date": "2025-12-05",
                              "accession": "0000754811-25-000010",
                              "primary_doc": "f4.xml", "cik": 754811}]), \
         patch("argus.collectors.edgar._fetch_form4_xml",
               return_value=_FORM4_PURCHASE), \
         patch("argus.collectors.edgar.get_spot_price",
               side_effect=Exception("no price")):
        n = collect_edgar_insider(session, _make_source(), "XOMA", 754811, _make_asset())
    assert n == 0


def test_collect_skips_old_filing():
    """Filings older than days_back are skipped entirely (no HTTP fetch)."""
    session = _make_session()
    old_filing = {"filing_date": "2019-05-06", "accession": "old-acc",
                  "primary_doc": "old.xml", "cik": 754811}
    with patch("argus.collectors.edgar._fetch_submissions",
               return_value=[old_filing]) as mock_sub, \
         patch("argus.collectors.edgar._fetch_form4_xml") as mock_fetch:
        n = collect_edgar_insider(session, _make_source(), "BYND", 12345,
                                  _make_asset("BYND"), days_back=365)
    assert n == 0
    mock_fetch.assert_not_called()
