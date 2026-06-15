"""EDGAR Form 4 insider purchase collector — direct from SEC, ~2 day lag."""
import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import httpx
from sqlalchemy import select

from argus.collectors.insider import InsiderTransaction, _confidence
from argus.models import Claim, ClaimAudit, Item, Source
from argus.prices import get_historical_price, get_spot_price

logger = logging.getLogger(__name__)

import os as _os
_EDGAR_EMAIL = _os.getenv("EDGAR_CONTACT_EMAIL", "kostrzew90@gmail.com")
_HEADERS = {
    "User-Agent": f"Argus/1.0 {_EDGAR_EMAIL}",
    "Accept": "application/json, text/xml, */*",
}
_BASE = "https://data.sec.gov"
_ARCHIVE = "https://www.sec.gov/Archives/edgar/data"
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_REQ_DELAY = 0.11   # EDGAR: 10 req/s max → 110ms between calls

# Module-level CIK cache (populated once per process)
_cik_cache: dict[str, int] = {}


def load_cik_map() -> dict[str, int]:
    """Fetch ticker→CIK from EDGAR company_tickers.json. ~10MB, cached in memory."""
    global _cik_cache
    if _cik_cache:
        return _cik_cache
    r = httpx.get(_TICKERS_URL, headers=_HEADERS, timeout=60)
    r.raise_for_status()
    _cik_cache = {v["ticker"].upper(): int(v["cik_str"]) for v in r.json().values()}
    logger.info("edgar: loaded %d CIKs", len(_cik_cache))
    return _cik_cache


def get_cik(ticker: str) -> int | None:
    return load_cik_map().get(ticker.upper())


def _make_edgar_ext_id(symbol: str, date_str: str, name: str, shares: int) -> str:
    raw = f"edgar_{symbol}_{date_str}_{name}_{shares}"
    return hashlib.md5(raw.encode()).hexdigest()


def _parse_submissions(data: dict) -> list[dict]:
    """Extract Form 4 filings from submissions JSON."""
    recent = data.get("filings", {}).get("recent", {})
    forms   = recent.get("form", [])
    dates   = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    docs    = recent.get("primaryDocument", [])
    cik_str = data.get("cik", "0")
    result = []
    for i, form in enumerate(forms):
        if form == "4":
            result.append({
                "form": "4",
                "filing_date": dates[i] if i < len(dates) else "",
                "accession": accessions[i] if i < len(accessions) else "",
                "primary_doc": docs[i] if i < len(docs) else "",
                "cik": int(cik_str),
            })
    return result


def _fetch_submissions(cik: int) -> list[dict]:
    url = f"{_BASE}/submissions/CIK{cik:010d}.json"
    time.sleep(_REQ_DELAY)
    r = httpx.get(url, headers=_HEADERS, timeout=30)
    r.raise_for_status()
    return _parse_submissions(r.json())


def _fetch_form4_xml(cik: int, accession: str, primary_doc: str) -> str:
    acc_clean = accession.replace("-", "")
    # Strip XSLT renderer prefix — raw XML is one level up
    doc = primary_doc.split("/")[-1] if "/" in primary_doc else primary_doc
    url = f"{_ARCHIVE}/{cik}/{acc_clean}/{doc}"
    time.sleep(_REQ_DELAY)
    r = httpx.get(url, headers=_HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def parse_form4_xml(xml: str) -> list[InsiderTransaction]:
    """Parse Form 4 XML; returns only open-market purchases (code P, acquired A)."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        logger.warning("form4 XML parse error: %s", e)
        return []

    ticker = (root.findtext(".//issuerTradingSymbol") or "").upper().strip()
    name = (root.findtext(".//rptOwnerName") or "").strip()
    role = (root.findtext(".//officerTitle") or "").strip()

    result = []
    for tx in root.findall(".//nonDerivativeTransaction"):
        try:
            code = (tx.findtext(".//transactionCode") or "").strip()
            adc  = (tx.findtext(".//transactionAcquiredDisposedCode/value") or "").strip()
            if code != "P" or adc != "A":
                continue

            date_str = (tx.findtext(".//transactionDate/value") or "").strip()
            shares   = int(float(tx.findtext(".//transactionShares/value") or "0"))
            price    = float(tx.findtext(".//transactionPricePerShare/value") or "0")
            date     = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            total    = shares * price

            ext_id = _make_edgar_ext_id(ticker, date_str.replace("-", ""), name, shares)
            result.append(InsiderTransaction(
                date=date, insider_name=name, role=role,
                transaction_type="Purchase", shares=shares,
                price=price, total_value=total, external_id=ext_id,
            ))
        except Exception as e:
            logger.debug("form4 tx parse error: %s", e)

    return result


def collect_edgar_insider(session, source: Source, symbol: str,
                          cik: int, asset) -> int:
    now = datetime.now(timezone.utc)
    try:
        filings = _fetch_submissions(cik)
    except Exception as e:
        logger.warning("edgar submissions failed %s: %s", symbol, e)
        return 0

    created = 0
    for filing in filings:
        if not filing.get("primary_doc", "").endswith(".xml"):
            continue
        try:
            xml = _fetch_form4_xml(cik, filing["accession"], filing["primary_doc"])
        except Exception as e:
            logger.debug("edgar fetch form4 failed %s %s: %s",
                         symbol, filing["accession"], e)
            continue

        for tx in parse_form4_xml(xml):
            if tx.total_value < 10_000:
                continue
            existing = session.scalar(
                select(Item).where(
                    Item.source_id == source.id,
                    Item.external_id == tx.external_id,
                )
            )
            if existing is not None:
                continue

            item = Item(
                source_id=source.id,
                external_id=tx.external_id,
                title=f"[SEC] {tx.insider_name} ({tx.role}) bought {tx.shares:,} {symbol}",
                text=(f"SEC Form 4: {tx.insider_name} ({tx.role}) purchased "
                      f"{tx.shares:,} shares of {symbol} at ${tx.price:.2f} "
                      f"(total ${tx.total_value:,.0f}) on {tx.date.date()}. "
                      f"Filed {filing['filing_date']}."),
                published_at=tx.date,
                fetched_at=now,
            )
            session.add(item)
            session.flush()

            # entry anchored to transaction date — not detection time
            try:
                entry_price = get_historical_price(asset, tx.date)
            except Exception:
                try:
                    entry_price = get_spot_price(asset)
                except Exception as e:
                    logger.warning("edgar: no price for %s: %s", symbol, e)
                    continue

            claim = Claim(
                source_id=source.id, item_id=item.id,
                asset=symbol, direction="bull",
                confidence=_confidence(tx.total_value),
                method="insider", entry_price=entry_price,
                entry_ts=tx.date, status="open",
            )
            session.add(claim)
            session.flush()
            session.add(ClaimAudit(
                claim_id=claim.id,
                raw_text=item.text,
                parsed_claim={
                    "source": "edgar",
                    "accession": filing["accession"],
                    "type": "P",
                    "value_usd": tx.total_value,
                    "insider": tx.insider_name,
                    "role": tx.role,
                },
                parser_version="edgar-v1",
            ))
            created += 1

    session.commit()
    logger.info("edgar collect %s: %d new claims", symbol, created)
    return created
