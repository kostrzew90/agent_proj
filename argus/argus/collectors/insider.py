import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select

from argus.models import Asset, Claim, ClaimAudit, Item, Source
from argus.prices import get_historical_price, get_spot_price

logger = logging.getLogger(__name__)

_MB_BASE = "https://www.marketbeat.com/stocks"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Argus/1.0 contact@argus)",
    "Accept-Language": "en-US,en;q=0.9",
}
_MIN_VALUE_USD = 10_000

_EXCHANGE: dict[str, str] = {
    "BYND": "NASDAQ",
    "DLNG": "NYSE",
    "LCID": "NASDAQ",
    "NFE":  "NASDAQ",
    "NTR":  "NYSE",
    "PLG":  "NYSE",
    "XAI":  "NYSE",
    "XOMA": "NASDAQ",
}


@dataclass
class InsiderTransaction:
    date: datetime
    insider_name: str
    role: str
    transaction_type: str
    shares: int
    price: float
    total_value: float
    external_id: str


def _parse_value(text: str) -> float:
    t = text.replace("$", "").replace(",", "").strip().lower()
    if not t:
        return 0.0
    if "billion" in t:
        return float(t.replace("billion", "").strip()) * 1e9
    if "million" in t:
        return float(t.replace("million", "").strip()) * 1e6
    return float(t)


def _parse_shares(text: str) -> int:
    return int(text.replace(",", "").replace("shares", "").strip() or 0)


def _confidence(total_value: float) -> float:
    if total_value < 50_000:
        return 0.45
    if total_value < 500_000:
        return 0.50
    if total_value < 5_000_000:
        return 0.55
    if total_value < 50_000_000:
        return 0.60
    return 0.65


def _make_ext_id(symbol: str, date_str: str, name: str, shares: int, tx_type: str) -> str:
    raw = f"{symbol}_{date_str}_{name}_{shares}_{tx_type}"
    return hashlib.md5(raw.encode()).hexdigest()


def parse_insider_table(symbol: str, html: str) -> list[InsiderTransaction]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="scroll-table")
    if not table:
        return []
    tbody = table.find("tbody")
    if not tbody:
        return []
    result = []
    for row in tbody.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 6:
            continue
        try:
            date_val = cells[0].get("data-sort-value", "")
            if not date_val or len(date_val) < 8:
                continue
            date = datetime.strptime(date_val[:8], "%Y%m%d").replace(tzinfo=timezone.utc)

            data_clean = cells[1].get("data-clean", "") or ""
            parts = data_clean.split("|")
            name = parts[0].strip() if parts else cells[1].get_text(strip=True)
            role = parts[1].strip() if len(parts) > 1 else ""

            tx_type = cells[2].get_text(strip=True)
            shares = _parse_shares(cells[3].get_text(strip=True))
            price = _parse_value(cells[4].get_text(strip=True))
            total = _parse_value(cells[5].get_text(strip=True))

            ext_id = _make_ext_id(symbol, date_val[:8], name, shares, tx_type)
            result.append(InsiderTransaction(
                date=date, insider_name=name, role=role,
                transaction_type=tx_type, shares=shares,
                price=price, total_value=total, external_id=ext_id,
            ))
        except Exception as e:
            logger.debug("insider row parse error: %s", e)
    return result


def scrape_insider_trades(symbol: str) -> list[InsiderTransaction]:
    exchange = _EXCHANGE.get(symbol.upper(), "NASDAQ")
    url = f"{_MB_BASE}/{exchange}/{symbol}/insider-trades/"
    r = httpx.get(url, headers=_HEADERS, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return parse_insider_table(symbol, r.text)


def _is_purchase(tx_type: str) -> bool:
    t = tx_type.lower()
    return "buy" in t or "purchase" in t


def collect_insider(session, source: Source, symbol: str, asset) -> int:
    now = datetime.now(timezone.utc)
    try:
        transactions = scrape_insider_trades(symbol)
    except Exception as e:
        logger.warning("insider scrape failed %s: %s", symbol, e)
        return 0

    created = 0
    for tx in transactions:
        if not _is_purchase(tx.transaction_type):
            continue
        if tx.total_value < _MIN_VALUE_USD:
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
            title=f"{tx.insider_name} ({tx.role}) bought {tx.shares:,} {symbol} @ ${tx.price:.2f}",
            text=(f"Insider purchase: {tx.insider_name} ({tx.role}) bought {tx.shares:,} "
                  f"shares of {symbol} for ${tx.total_value:,.0f} on {tx.date.date()}"),
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
                logger.warning("insider: no price for %s: %s", symbol, e)
                continue

        conf = _confidence(tx.total_value)
        claim = Claim(
            source_id=source.id, item_id=item.id,
            asset=symbol, direction="bull",
            confidence=conf, method="insider",
            entry_price=entry_price, entry_ts=tx.date,
            status="open",
        )
        session.add(claim)
        session.flush()
        session.add(ClaimAudit(
            claim_id=claim.id,
            raw_text=item.text,
            parsed_claim={
                "type": tx.transaction_type,
                "value_usd": tx.total_value,
                "insider": tx.insider_name,
                "role": tx.role,
            },
            parser_version="insider-v1",
        ))
        created += 1

    session.commit()
    logger.info("insider collect %s: %d new claims", symbol, created)
    return created
