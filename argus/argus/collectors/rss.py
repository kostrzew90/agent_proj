import os
import re
import calendar
import logging
from datetime import datetime, timezone
from dataclasses import asdict
import yaml
import feedparser
from sqlalchemy import select
from argus.models import Asset, Item, Claim, ClaimAudit
from argus.extract import extract_claims, PARSER_VERSION
from argus.prices import get_spot_price
from argus.llm.batch import enqueue_for_llm

logger = logging.getLogger(__name__)

_REDDIT_UA = "linux:argus-trend-monitor:1.0 (personal research bot)"


def load_sector_map(path: str = "config/sectors.yaml") -> dict:
    if os.path.exists(path):
        return yaml.safe_load(open(path, encoding="utf-8")) or {}
    return {}


def _build_watchlist_pattern(assets, sector_map: dict) -> re.Pattern | None:
    """Compile a single word-boundary regex matching any watchlist symbol
    (incl. optional $ cashtag prefix) or sector alias. Returns None if no
    terms are known (pre-filter then never matches, caller should treat
    that as "let it through" upstream if desired)."""
    terms = {re.escape(a.symbol) for a in assets if a.symbol}
    for sec in (sector_map or {}).values():
        terms.update(re.escape(alias) for alias in sec.get("aliases", []))
    if not terms:
        return None
    joined = "|".join(sorted(terms, key=len, reverse=True))
    return re.compile(rf"(?<![a-z0-9])\$?(?:{joined})(?![a-z0-9])", re.IGNORECASE)


def _mentions_watchlist(text: str, pattern: "re.Pattern | None") -> bool:
    """True if text mentions a watchlist asset symbol or sector alias.
    `pattern` is a precompiled regex from _build_watchlist_pattern, built
    once per collect_rss call rather than per item."""
    return bool(pattern and pattern.search(text))


def _published(entry):
    pp = getattr(entry, "published_parsed", None)
    if not pp:
        return None
    return datetime.fromtimestamp(calendar.timegm(pp), tz=timezone.utc)


def _add_claim(session, source, item, asset_symbol, direction, confidence, method,
               parser_version, parsed_claim, raw_text, entry_price, now):
    claim = Claim(source_id=source.id, item_id=item.id, asset=asset_symbol,
                  direction=direction, confidence=confidence, method=method,
                  entry_price=entry_price, entry_ts=now, status="open")
    session.add(claim); session.flush()
    session.add(ClaimAudit(claim_id=claim.id, raw_text=raw_text,
                           parsed_claim=parsed_claim, parser_version=parser_version))


def collect_rss(session, source) -> int:
    if source.kind == "reddit":
        feed = feedparser.parse(source.handle, agent=_REDDIT_UA)
    else:
        feed = feedparser.parse(source.handle)
    status = getattr(feed, "status", None)
    if isinstance(status, int) and status >= 400:
        logger.warning("collect_rss %s: HTTP %s", source.display_name, status)
    assets = list(session.scalars(select(Asset).where(Asset.scorable == True)))  # noqa: E712
    by_symbol = {a.symbol: a for a in assets}
    sector_map = load_sector_map()
    watchlist_pattern = _build_watchlist_pattern(assets, sector_map)
    now = datetime.now(timezone.utc)
    created = 0
    stats = {"items": 0, "enqueued": 0, "rule_claims": 0, "enqueue_skipped": 0}
    for entry in feed.entries:
        ext = getattr(entry, "id", None) or getattr(entry, "link", None)
        if ext is None:
            continue
        if session.scalar(select(Item).where(Item.source_id == source.id, Item.external_id == ext)):
            continue
        text = f"{getattr(entry, 'title', '')} {getattr(entry, 'summary', '')}"
        item = Item(source_id=source.id, external_id=ext, title=getattr(entry, "title", None),
                    text=text, url=getattr(entry, "link", None),
                    published_at=_published(entry), fetched_at=now)
        session.add(item); session.flush()
        created += 1; stats["items"] += 1

        rule_pcs = extract_claims(text, assets, sector_map=sector_map)
        if rule_pcs:
            for pc in rule_pcs:
                asset = by_symbol[pc.asset_symbol]
                try:
                    spot = get_spot_price(asset)
                except Exception as e:
                    logger.warning("skip rule claim %s: price failed: %s", pc.asset_symbol, e); continue
                _add_claim(session, source, item, asset.symbol, pc.direction, pc.confidence,
                           "rule", PARSER_VERSION, asdict(pc), text, spot, now)
                stats["rule_claims"] += 1
        elif source.kind in ("reddit", "news"):
            if _mentions_watchlist(text, watchlist_pattern):
                enqueue_for_llm(session, item, source.kind, text)
                stats["enqueued"] += 1
            else:
                stats["enqueue_skipped"] += 1
    session.commit()
    logger.info("collect_rss %s: %s", source.display_name, stats)
    return created
