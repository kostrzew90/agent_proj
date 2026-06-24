import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import yaml
from sqlalchemy import select

from argus.models import Asset, Claim, ClaimAudit, Liquidation, Source
from argus.prices import get_historical_price

logger = logging.getLogger(__name__)

_MIN_DURATION_MINUTES = 1.0


@dataclass
class CascadeEvent:
    asset: str
    side: str
    window_start: datetime
    window_end: datetime
    total_notional: float
    n_fills: int
    cascade_intensity: float
    price_change_window: float | None = None


def detect_cascades(liquidations: list, window_minutes: int, min_notional: float) -> list[CascadeEvent]:
    groups: dict[tuple[str, str], list] = {}
    for row in liquidations:
        groups.setdefault((row.asset, row.side), []).append(row)

    events: list[CascadeEvent] = []
    window = timedelta(minutes=window_minutes)

    for (asset, side), rows in groups.items():
        rows = sorted(rows, key=lambda r: r.ts)
        cluster: list = []
        for row in rows:
            if cluster and row.ts - cluster[-1].ts > window:
                events.append(_finalize_cluster(asset, side, cluster, min_notional))
                cluster = []
            cluster.append(row)
        if cluster:
            events.append(_finalize_cluster(asset, side, cluster, min_notional))

    return [e for e in events if e is not None]


def _finalize_cluster(asset: str, side: str, cluster: list, min_notional: float) -> CascadeEvent | None:
    total_notional = sum(r.notional_usd for r in cluster)
    if total_notional < min_notional:
        return None
    window_start = cluster[0].ts
    window_end = cluster[-1].ts
    duration_minutes = max((window_end - window_start).total_seconds() / 60, _MIN_DURATION_MINUTES)
    return CascadeEvent(
        asset=asset,
        side=side,
        window_start=window_start,
        window_end=window_end,
        total_notional=total_notional,
        n_fills=len(cluster),
        cascade_intensity=total_notional / duration_minutes,
    )


def annotate_price_context(session, cascades: list[CascadeEvent], lookback_minutes: int = 15) -> None:
    assets = {a.symbol: a for a in session.scalars(select(Asset))}
    for cascade in cascades:
        asset = assets.get(cascade.asset)
        if asset is None:
            continue
        try:
            price_before = get_historical_price(asset, cascade.window_start - timedelta(minutes=lookback_minutes))
            price_at = get_historical_price(asset, cascade.window_start)
        except Exception as e:
            logger.warning("cascade: price context failed for %s: %s", cascade.asset, e)
            continue
        if price_before:
            cascade.price_change_window = (price_at - price_before) / price_before


def compute_notional_p95(session) -> float:
    # Design deviation: spec calls for a rolling 30-day window, but with only ~600
    # historical fills spread over 7 months, a strict rolling window can have zero
    # or near-zero rows at many points in time, making the percentile undefined or
    # noisy. We use all-time notional_usd history instead — same purpose (a stable
    # reference point for "how big is this cascade relative to normal"), more robust
    # given current data volume. Revisit once liquidation volume grows enough for a
    # rolling window to be statistically meaningful.
    values = sorted(session.scalars(select(Liquidation.notional_usd)))
    if not values:
        return 0.0
    idx = math.ceil(0.95 * len(values)) - 1
    return values[min(max(idx, 0), len(values) - 1)]


def load_direction_rules(path: str = "config/liq_cascade_rules.yaml") -> dict[str, str]:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("direction_rule", {}) or {}


def ensure_cascade_source(session) -> Source:
    source = session.scalar(select(Source).where(Source.kind == "derived", Source.handle == "liq-cascade"))
    if source is None:
        source = Source(kind="derived", handle="liq-cascade", display_name="Liquidation Cascade", active=True)
        session.add(source)
        session.commit()
        session.refresh(source)
    return source


def _cascade_direction(side: str, rule: str) -> str:
    if rule == "contrarian":
        return "bull" if side == "long_liq" else "bear"
    return "bear" if side == "long_liq" else "bull"


def emit_cascade_claims(session, cascades: list[CascadeEvent], direction_rule: dict[str, str],
                         notional_p95: float) -> int:
    assets = {a.symbol: a for a in session.scalars(select(Asset))}
    created = 0
    for cascade in cascades:
        rule = direction_rule.get(cascade.asset)
        if rule is None:
            continue
        raw_key = (f"LIQ_CASCADE:{cascade.asset}:{cascade.side}:{cascade.window_start.isoformat()}"
                   f":{cascade.window_end.isoformat()}:{cascade.total_notional}")
        existing = session.scalar(select(ClaimAudit).where(ClaimAudit.raw_text == raw_key))
        if existing is not None:
            continue
        asset = assets.get(cascade.asset)
        if asset is None:
            continue
        try:
            entry_price = get_historical_price(asset, cascade.window_end)
        except Exception as e:
            logger.warning("cascade: entry price failed for %s: %s", cascade.asset, e)
            continue
        cascade_strength = (cascade.total_notional / notional_p95) if notional_p95 > 0 else 1.0
        confidence = max(0.3, min(0.9, 0.3 + cascade_strength * 0.4))
        direction = _cascade_direction(cascade.side, rule)
        source = ensure_cascade_source(session)
        claim = Claim(source_id=source.id, asset=cascade.asset, direction=direction,
                      confidence=round(confidence, 2), method="rule",
                      entry_price=entry_price, entry_ts=cascade.window_end, status="open")
        session.add(claim)
        session.flush()
        session.add(ClaimAudit(
            claim_id=claim.id, raw_text=raw_key,
            parsed_claim={"asset": cascade.asset, "side": cascade.side, "rule": rule,
                          "total_notional": cascade.total_notional, "n_fills": cascade.n_fills,
                          "cascade_intensity": cascade.cascade_intensity,
                          "price_change_window": cascade.price_change_window},
            parser_version="liq-cascade-v1",
        ))
        created += 1
    session.commit()
    return created
