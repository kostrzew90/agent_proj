import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import prod
from sqlalchemy import select, func

from argus.models import (
    Asset, Claim, Price, Source, SourceScore, SourceAssetScore,
    SignalLog, SignalOutcome, WalletPosition,
)
from argus.telegram import send_message
from argus.prices import get_spot_price

logger = logging.getLogger(__name__)

_GATE_MIN_EXCESS = 0.08
_GATE_MIN_CLAIMS = 5
# In the post-Increment-A scale, the maximum effective strength of a single
# source is 0.370, and the best real three-source combination on production
# data is 0.476 — 0.80 was unreachable. 0.30 is a floor that filters out
# pairs of weak sources without being a binding constraint; the actual
# confluence filter is the 2h window + the per-source gate.
_CONFLUENCE_MIN_STRENGTH = 0.30
_CONFLUENCE_MAX_SIGNALS = 3
_COOLDOWN_HOURS = 2
_WHALE_LOOKBACK_MINUTES = 20
_CONFLUENCE_WINDOW_HOURS = 2
_ELIGIBLE_KINDS = {"hyperliquid", "reddit", "news", "rss"}
_PRICE_CACHE_MAX_AGE_MINUTES = 15

_VOL_TIER_MAP = {"BTC": "large", "ETH": "large"}

_STOP_PCT_MAP = {
    ("large", "crypto"): 0.05,
    ("large", "stock"):  0.03,
    ("mid",   "crypto"): 0.07,
    ("mid",   "stock"):  0.04,
    ("small", "crypto"): 0.10,
    ("small", "stock"):  0.05,
}


@dataclass
class SignalResult:
    tier: str
    asset: str
    asset_kind: str
    direction: str
    source_ids: list
    source_labels: list
    signal_strength: float
    entry_price: float
    stop_price: float
    position_pct: float
    risk_pct: float
    stop_pct: float
    vol_tier: str
    horizon: str
    window_str: str | None
    whale_notional: float | None
    fng_value: int | None = None
    fng_adjusted: bool = False


def passes_gate(decayed_score: float, n_claims: int, cohort_rate: float) -> bool:
    """Gate on the source's edge over its cohort, not on an absolute score.
    Since Increment A the prior is anchored in the cohort baseline, so an
    absolute threshold no longer means anything."""
    return (decayed_score - cohort_rate) >= _GATE_MIN_EXCESS and n_claims >= _GATE_MIN_CLAIMS


def effective_score(decayed_score: float, n_claims: int) -> float:
    return decayed_score * min(1.0, n_claims / 30)


def combined_strength(scores: list) -> float:
    if not scores:
        return 0.0
    return 1.0 - prod(1.0 - s for s in scores)


def vol_tier(symbol: str) -> str:
    return _VOL_TIER_MAP.get(symbol, "mid")


def _stop_pct(vt: str, asset_kind: str) -> float:
    return _STOP_PCT_MAP.get((vt, asset_kind), _STOP_PCT_MAP[("mid", "crypto")])


def _risk_pct(strength: float) -> float:
    if strength >= 0.45:
        return 0.03
    if strength >= 0.35:
        return 0.02
    return 0.01


def compute_sizing(strength: float, asset_symbol: str, asset_kind: str) -> dict:
    vt = vol_tier(asset_symbol)
    sp = _stop_pct(vt, asset_kind)
    rp = _risk_pct(strength)
    pos = rp / sp
    if asset_kind == "stock":
        pos = min(pos, 0.15)
    return {"risk_pct": rp, "stop_pct": sp, "position_pct": pos, "vol_tier": vt}


def apply_fear_greed(result, fng: int | None):
    """Crypto only: record sentiment; halve sizing when the signal follows the crowd at an extreme."""
    if result.asset_kind != "crypto" or fng is None:
        return result
    result.fng_value = fng
    if (fng >= 75 and result.direction == "bull") or (fng <= 25 and result.direction == "bear"):
        result.position_pct /= 2
        result.risk_pct /= 2
        result.fng_adjusted = True
    return result


def _fng_label(value: int) -> str:
    if value <= 25:
        return "skrajny strach"
    if value <= 45:
        return "strach"
    if value <= 55:
        return "neutralnie"
    if value < 75:
        return "chciwość"
    return "skrajna chciwość"


def _is_on_cooldown(session, asset: str) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=_COOLDOWN_HOURS)
    return session.scalar(
        select(SignalLog).where(SignalLog.asset == asset, SignalLog.sent_at >= cutoff)
    ) is not None


def _max_n_claims(session, source_id: int) -> int:
    return session.scalar(
        select(func.max(SourceScore.n_claims)).where(
            SourceScore.source_id == source_id, SourceScore.direction == "all")
    ) or 0


def _get_source_score(session, source_id: int, horizon: str):
    return session.scalar(
        select(SourceScore).where(
            SourceScore.source_id == source_id,
            SourceScore.horizon == horizon,
            SourceScore.direction == "all",
        )
    )


def _get_source_asset_score(session, source_id: int, asset: str, horizon: str):
    return session.scalar(
        select(SourceAssetScore).where(
            SourceAssetScore.source_id == source_id,
            SourceAssetScore.asset == asset,
            SourceAssetScore.horizon == horizon,
            SourceAssetScore.direction == "all",
        )
    )


def _last_price(session, asset: str):
    row = session.scalar(
        select(Price).where(Price.asset == asset).order_by(Price.ts.desc())
    )
    if row is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=_PRICE_CACHE_MAX_AGE_MINUTES)
        if row.ts >= cutoff:
            return row.price

    asset_row = session.get(Asset, asset)
    if asset_row is None:
        return None

    try:
        price = get_spot_price(asset_row)
    except Exception as exc:
        logger.warning("last_price: spot fetch failed for %s: %s", asset, exc)
        return None

    session.add(Price(asset=asset, ts=datetime.now(timezone.utc), price=price))
    session.commit()
    return price


def _save_signal(session, result) -> SignalLog:
    log = SignalLog(
        tier=result.tier,
        asset=result.asset,
        direction=result.direction,
        source_ids=json.dumps(result.source_ids),
        signal_strength=result.signal_strength,
        entry_price=result.entry_price,
        stop_price=result.stop_price,
        position_pct=result.position_pct,
        sent_at=datetime.now(timezone.utc),
        fng_value=result.fng_value,
    )
    session.add(log)
    session.flush()
    session.add(SignalOutcome(
        signal_id=log.id,
        asset=result.asset,
        entry_price=result.entry_price,
        outcome="open",
    ))
    session.commit()
    return log


def check_whale_signals(session) -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=_WHALE_LOOKBACK_MINUTES)
    positions = list(session.scalars(
        select(WalletPosition).where(
            WalletPosition.open == True,   # noqa: E712
            WalletPosition.opened_ts >= cutoff,
        )
    ))
    results = []
    for pos in positions:
        source = session.get(Source, pos.source_id)
        if source is None or source.kind != "hyperliquid":
            continue
        # A signal on a coin outside the `assets` table can't be priced or
        # scored — _last_price would return None for it, so its
        # SignalOutcome would stay "open" forever. check_liquidation_signals
        # already has this same gate; this makes whale consistent with it.
        asset_row = session.scalar(select(Asset).where(Asset.symbol == pos.coin))
        if asset_row is None:
            continue
        n = _max_n_claims(session, pos.source_id)
        ss = _get_source_score(session, pos.source_id, "24h")
        if ss is None or not passes_gate(ss.decayed_score, n, ss.cohort_rate):
            continue
        if _is_on_cooldown(session, pos.coin):
            continue
        eff = effective_score(ss.decayed_score, n)
        sizing = compute_sizing(eff, pos.coin, asset_row.kind)
        direction = "bull" if pos.side == "long" else "bear"
        sp = sizing["stop_pct"]
        stop = pos.entry_px * (1 - sp) if direction == "bull" else pos.entry_px * (1 + sp)
        label = (f"{source.display_name} · {ss.decayed_score:.2f} · "
                 f"{ss.hit_rate:.0%}@24h · n={n}")
        results.append(SignalResult(
            tier="whale",
            asset=pos.coin,
            asset_kind=asset_row.kind,
            direction=direction,
            source_ids=[pos.source_id],
            source_labels=[label],
            signal_strength=eff,
            entry_price=pos.entry_px,
            stop_price=round(stop, 4),
            position_pct=sizing["position_pct"],
            risk_pct=sizing["risk_pct"],
            stop_pct=sizing["stop_pct"],
            vol_tier=sizing["vol_tier"],
            horizon="24h",
            window_str=None,
            whale_notional=pos.position_value,
        ))
    return results


def check_liquidation_signals(session) -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=_WHALE_LOOKBACK_MINUTES)
    source = session.scalar(select(Source).where(Source.kind == "derived", Source.handle == "liq-cascade"))
    if source is None:
        return []
    claims = list(session.scalars(
        select(Claim).where(Claim.source_id == source.id, Claim.entry_ts >= cutoff)
    ))
    results = []
    for claim in claims:
        asset_row = session.scalar(select(Asset).where(Asset.symbol == claim.asset))
        if asset_row is None:
            continue
        ss = _get_source_asset_score(session, source.id, claim.asset, "24h")
        if ss is None or not passes_gate(ss.decayed_score, ss.n_claims, ss.cohort_rate):
            continue
        if _is_on_cooldown(session, claim.asset):
            continue
        eff = effective_score(ss.decayed_score, ss.n_claims)
        sizing = compute_sizing(eff, claim.asset, asset_row.kind)
        sp = sizing["stop_pct"]
        stop = claim.entry_price * (1 - sp) if claim.direction == "bull" else claim.entry_price * (1 + sp)
        label = f"Liquidation Cascade · {ss.decayed_score:.2f} · {ss.hit_rate:.0%}@24h · n={ss.n_claims}"
        results.append(SignalResult(
            tier="liq_cascade",
            asset=claim.asset,
            asset_kind=asset_row.kind,
            direction=claim.direction,
            source_ids=[source.id],
            source_labels=[label],
            signal_strength=eff,
            entry_price=claim.entry_price,
            stop_price=round(stop, 4),
            position_pct=sizing["position_pct"],
            risk_pct=sizing["risk_pct"],
            stop_pct=sizing["stop_pct"],
            vol_tier=sizing["vol_tier"],
            horizon="24h",
            window_str=None,
            whale_notional=None,
        ))
    return results


def check_confluence_signals(session) -> list:
    window_cutoff = datetime.now(timezone.utc) - timedelta(hours=_CONFLUENCE_WINDOW_HOURS)
    claims = list(session.scalars(
        select(Claim).where(Claim.entry_ts >= window_cutoff)
    ))

    groups: dict = {}
    for claim in claims:
        source = session.get(Source, claim.source_id)
        if source is None or source.kind not in _ELIGIBLE_KINDS:
            continue
        asset_row = session.scalar(select(Asset).where(Asset.symbol == claim.asset))
        if asset_row is None:
            continue
        horizon = "7d" if asset_row.kind == "stock" else "24h"
        n = _max_n_claims(session, claim.source_id)
        ss = _get_source_score(session, claim.source_id, horizon)
        if ss is None or not passes_gate(ss.decayed_score, n, ss.cohort_rate):
            continue
        key = (claim.asset, claim.direction)
        groups.setdefault(key, []).append((claim, source, ss, n, asset_row))

    results = []
    for (asset, direction), entries in groups.items():
        kinds = {e[1].kind for e in entries}
        if len(kinds) < 2:
            continue
        if _is_on_cooldown(session, asset):
            continue
        asset_row = entries[0][4]
        horizon = "7d" if asset_row.kind == "stock" else "24h"
        eff_scores = [e[2].decayed_score * min(1.0, e[3] / 7.0) for e in entries]
        strength = combined_strength(eff_scores)
        if strength < _CONFLUENCE_MIN_STRENGTH:
            continue
        entry_price = _last_price(session, asset)
        if entry_price is None:
            logger.warning("confluence: no price for %s, skipping", asset)
            continue
        sizing = compute_sizing(strength, asset, asset_row.kind)
        sp = sizing["stop_pct"]
        stop = entry_price * (1 - sp) if direction == "bull" else entry_price * (1 + sp)
        timestamps = [e[0].entry_ts for e in entries]
        window_mins = int((max(timestamps) - min(timestamps)).total_seconds() / 60)
        window_str = (f"{window_mins // 60}h{window_mins % 60}m"
                      if window_mins >= 60 else f"{window_mins}m")
        labels = [
            f"{e[1].display_name} · {e[2].decayed_score:.2f} · "
            f"{e[2].hit_rate:.0%}@{horizon} · n={e[3]}"
            for e in entries
        ]
        results.append(SignalResult(
            tier="confluence",
            asset=asset,
            asset_kind=asset_row.kind,
            direction=direction,
            source_ids=[e[0].source_id for e in entries],
            source_labels=labels,
            signal_strength=strength,
            entry_price=entry_price,
            stop_price=round(stop, 4),
            position_pct=sizing["position_pct"],
            risk_pct=sizing["risk_pct"],
            stop_pct=sizing["stop_pct"],
            vol_tier=sizing["vol_tier"],
            horizon=horizon,
            window_str=window_str,
            whale_notional=None,
        ))

    results.sort(key=lambda r: r.signal_strength, reverse=True)
    return results[:_CONFLUENCE_MAX_SIGNALS]


def evaluate_signal_outcomes(session) -> int:
    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)
    open_outcomes = list(session.scalars(
        select(SignalOutcome)
        .join(SignalLog, SignalOutcome.signal_id == SignalLog.id)
        .where(SignalOutcome.outcome == "open")
        .where(SignalLog.sent_at <= cutoff_24h)
    ))
    updated = 0
    for so in open_outcomes:
        signal = session.get(SignalLog, so.signal_id)
        current_price = _last_price(session, so.asset)
        if current_price is None:
            continue
        age_hours = (now - signal.sent_at).total_seconds() / 3600
        if age_hours >= 24 and so.price_24h is None:
            so.price_24h = current_price
        if age_hours >= 168 and so.price_7d is None:
            so.price_7d = current_price
        if signal.direction == "bull":
            hit_stop = current_price <= signal.stop_price
        else:
            hit_stop = current_price >= signal.stop_price
        if hit_stop:
            so.hit_stop = True
            so.outcome = "stopped"
        elif so.price_7d is not None:
            ret = (so.price_7d - so.entry_price) / so.entry_price
            so.outcome = "win" if (signal.direction == "bull") == (ret > 0) else "loss"
        so.evaluated_at = now
        updated += 1
    session.commit()
    return updated


def send_signals(session) -> None:
    whale = check_whale_signals(session)
    confluence = check_confluence_signals(session)
    liq_cascade = check_liquidation_signals(session)
    try:
        from argus.collectors.fear_greed import get_current_fng
        fng = get_current_fng(session)
    except Exception as exc:
        session.rollback()
        logger.warning("fear&greed unavailable: %s", exc)
        fng = None
    for result in whale + confluence + liq_cascade:
        apply_fear_greed(result, fng)
        msg = format_signal_message(result)
        send_message(msg)
        log = _save_signal(session, result)
        try:
            from argus import paper
            paper.open_trade(session, log, result.asset_kind)
        except Exception as exc:
            session.rollback()
            logger.warning("paper trade failed for %s: %s", result.asset, exc)
        logger.info("signal sent: %s %s %s strength=%.2f",
                    result.tier, result.direction, result.asset, result.signal_strength)


def format_signal_message(result) -> str:
    emoji = {"whale": "🐋", "confluence": "⚡", "liq_cascade": "🌊"}[result.tier]
    dir_str = "BULLISH" if result.direction == "bull" else "BEARISH"
    suffix = "USDT" if result.asset_kind == "crypto" else "USD"
    if result.tier == "whale":
        tier_str = "WHALE SIGNAL"
    elif result.tier == "confluence":
        tier_str = f"CONFLUENCE · strength {result.signal_strength:.2f}"
    else:
        tier_str = f"LIQUIDATION CASCADE · strength {result.signal_strength:.2f}"
    lines = [f"{emoji} {tier_str} · {dir_str} {result.asset}/{suffix}", ""]
    for label in result.source_labels:
        lines.append(f"• {label}")
    if result.tier == "confluence" and result.window_str:
        lines.append(f"Zgodność: {len(result.source_ids)} źródła · okno {result.window_str}")
    if result.whale_notional is not None:
        lines.append(f"Pozycja whale: ${result.whale_notional:,.0f} @ ${result.entry_price:.2f}")
    lines += [
        "",
        f"Entry teraz: ~${result.entry_price:.2f}",
        f"Stop-loss: ${result.stop_price:.2f} (-{result.stop_pct:.0%}, {result.vol_tier} cap)",
        f"Pozycja: {result.position_pct:.0%} portfela (ryzyko {result.risk_pct:.0%})",
        f"Horyzont: {result.horizon}",
    ]
    if result.fng_value is not None:
        lines.append(f"Fear & Greed: {result.fng_value} ({_fng_label(result.fng_value)})")
    if result.fng_adjusted:
        lines.append("⚠️ Sygnał zgodny z tłumem przy skrajnym nastroju — pozycja zmniejszona o połowę")
    return "\n".join(lines)
