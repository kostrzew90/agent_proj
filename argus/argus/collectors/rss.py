import os
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


def load_sector_map(path: str = "config/sectors.yaml") -> dict:
    if os.path.exists(path):
        return yaml.safe_load(open(path, encoding="utf-8")) or {}
    return {}


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
    feed = feedparser.parse(source.handle)
    assets = list(session.scalars(select(Asset).where(Asset.scorable == True)))  # noqa: E712
    by_symbol = {a.symbol: a for a in assets}
    sector_map = load_sector_map()
    now = datetime.now(timezone.utc)
    created = 0
    stats = {"items": 0, "enqueued": 0, "rule_claims": 0}
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
            enqueue_for_llm(session, item, source.kind, text)
            stats["enqueued"] += 1
    session.commit()
    logger.info("collect_rss %s: %s", source.display_name, stats)
    return created
