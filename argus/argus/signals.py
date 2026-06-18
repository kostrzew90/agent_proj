import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import prod
from sqlalchemy import select, func

from argus.models import (
    Asset, Claim, Price, Source, SourceScore,
    SignalLog, SignalOutcome, WalletPosition,
)

logger = logging.getLogger(__name__)

_GATE_MIN_SCORE = 0.60
_GATE_MIN_CLAIMS = 5
_CONFLUENCE_MIN_STRENGTH = 0.80
_CONFLUENCE_MAX_SIGNALS = 3
_COOLDOWN_HOURS = 2
_WHALE_LOOKBACK_MINUTES = 10
_CONFLUENCE_WINDOW_HOURS = 2
_ELIGIBLE_KINDS = {"hyperliquid", "reddit", "news", "rss"}

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


def passes_gate(decayed_score: float, n_claims: int) -> bool:
    return decayed_score >= _GATE_MIN_SCORE and n_claims >= _GATE_MIN_CLAIMS


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
    if strength >= 0.90:
        return 0.03
    if strength >= 0.75:
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
