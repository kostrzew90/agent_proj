import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

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
