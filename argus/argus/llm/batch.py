import logging
import os
from datetime import datetime, timezone

from sqlalchemy import select, case

from argus.models import Claim, ClaimAudit, Item, LlmQueue
from argus.llm.cache import cache_get, cache_put, text_hash
from argus.llm.extractor import LLM_DEFAULT_CONFIDENCE, extract_claims_llm
from argus.prices import get_historical_price, get_spot_price

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = int(os.getenv("ARGUS_LLM_MAX_ATTEMPTS", "5"))


def enqueue_for_llm(session, item, source_kind: str, text: str) -> bool:
    h = text_hash(text)
    if session.scalar(select(LlmQueue).where(LlmQueue.item_id == item.id)):
        return False
    session.add(LlmQueue(
        item_id=item.id,
        text_hash=h,
        source_kind=source_kind,
        status="pending",
        attempts=0,
        enqueued_at=datetime.now(timezone.utc),
    ))
    return True


def process_llm_batch(session, batch_size: int, assets, sector_map) -> dict:
    by_symbol = {a.symbol: a for a in assets}

    pending = list(session.scalars(
        select(LlmQueue)
        .where(LlmQueue.status == "pending", LlmQueue.attempts < _MAX_ATTEMPTS)
        .order_by(
            case((LlmQueue.source_kind == "reddit", 0), else_=1).asc(),
            LlmQueue.enqueued_at.desc(),
        )
        .limit(batch_size)
    ))

    stats = {"processed": 0, "cache_hits": 0, "llm_calls": 0, "claims": 0, "errors": 0}

    for entry in pending:
        item = session.get(Item, entry.item_id)
        if item is None:
            entry.status = "failed"
            entry.last_error = "item not found"
            session.commit()
            stats["errors"] += 1
            continue

        cached = cache_get(session, entry.text_hash)
        if cached is not None:
            triples = [(c["asset"], c["direction"], c.get("reasoning", "")) for c in cached]
            stats["cache_hits"] += 1
        else:
            try:
                llm_claims = extract_claims_llm(item.text or "", assets, sector_map)
                cache_put(session, entry.text_hash,
                          [{"asset": c.asset_symbol, "direction": c.direction, "reasoning": c.reasoning}
                           for c in llm_claims])
                triples = [(c.asset_symbol, c.direction, c.reasoning) for c in llm_claims]
                stats["llm_calls"] += 1
            except Exception as e:
                entry.attempts += 1
                entry.last_error = str(e)[:300]
                if entry.attempts >= _MAX_ATTEMPTS:
                    entry.status = "failed"
                session.commit()
                stats["errors"] += 1
                continue

        ts = item.published_at or item.fetched_at or datetime.now(timezone.utc)

        for sym, direction, reasoning in triples:
            asset = by_symbol.get(sym)
            if asset is None:
                continue
            try:
                entry_price = get_historical_price(asset, ts)
            except Exception:
                try:
                    entry_price = get_spot_price(asset)
                except Exception as e2:
                    logger.warning("skip llm claim %s: price failed: %s", sym, e2)
                    continue

            claim = Claim(
                source_id=item.source_id,
                item_id=item.id,
                asset=sym,
                direction=direction,
                confidence=LLM_DEFAULT_CONFIDENCE,
                method="llm",
                entry_price=entry_price,
                entry_ts=ts,
                status="open",
            )
            session.add(claim)
            session.flush()
            session.add(ClaimAudit(
                claim_id=claim.id,
                raw_text=item.text or "",
                parsed_claim={"asset": sym, "direction": direction, "reasoning": reasoning},
                parser_version="llm-v1",
            ))
            stats["claims"] += 1

        entry.status = "done"
        entry.processed_at = datetime.now(timezone.utc)
        session.commit()
        stats["processed"] += 1

    return stats
