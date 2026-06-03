from datetime import datetime, timezone
import calendar
import logging
import feedparser
from sqlalchemy import select
from argus.models import Asset, Item, Claim, ClaimAudit
from argus.extract import extract_claims, PARSER_VERSION
from argus.prices import get_spot_price
from dataclasses import asdict

logger = logging.getLogger(__name__)


def _published(entry) -> datetime | None:
    pp = getattr(entry, "published_parsed", None)
    if not pp:
        return None
    return datetime.fromtimestamp(calendar.timegm(pp), tz=timezone.utc)


def collect_rss(session, source) -> int:
    feed = feedparser.parse(source.handle)
    assets = list(session.scalars(select(Asset).where(Asset.scorable == True)))  # noqa: E712
    by_symbol = {a.symbol: a for a in assets}
    created = 0
    now = datetime.now(timezone.utc)
    for entry in feed.entries:
        ext = getattr(entry, "id", None) or getattr(entry, "link", None)
        if ext is None:
            continue
        exists = session.scalar(select(Item).where(
            Item.source_id == source.id, Item.external_id == ext))
        if exists:
            continue
        text = f"{getattr(entry, 'title', '')} {getattr(entry, 'summary', '')}"
        item = Item(source_id=source.id, external_id=ext,
                    title=getattr(entry, "title", None), text=text,
                    url=getattr(entry, "link", None),
                    published_at=_published(entry), fetched_at=now)
        session.add(item); session.flush()
        created += 1
        for pc in extract_claims(text, assets):
            asset = by_symbol[pc.asset_symbol]
            try:
                entry_price = get_spot_price(asset)
            except Exception as e:
                logger.warning("skip claim for %s: price fetch failed: %s", asset.symbol, e)
                continue
            claim = Claim(source_id=source.id, item_id=item.id, asset=asset.symbol,
                          direction=pc.direction, target_price=pc.target_price,
                          confidence=pc.confidence, method="rule",
                          entry_price=entry_price, entry_ts=now, status="open")
            session.add(claim); session.flush()
            session.add(ClaimAudit(claim_id=claim.id, raw_text=text,
                                   parsed_claim=asdict(pc), parser_version=PARSER_VERSION))
    session.commit()
    return created
