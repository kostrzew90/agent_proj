# Argus Liquidation Cascade Signals — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the now-fixed `liquidations` table into a self-learning signal source (Tier 3 "liq_cascade") by emitting claims from detected liquidation cascades through the existing Claim/Source/SourceAssetScore pipeline, deciding the direction hypothesis (contrarian vs continuation) via backtest on the 600+ historical records before going live.

**Architecture:** A new pure-function cascade detector (`argus/liquidations/cascade.py`) groups raw `Liquidation` rows into cascade events, then emits them as `Claim`s from one synthetic `Source(kind="derived", handle="liq-cascade")`. The existing outcome evaluator, Bayesian scorer (`SourceAssetScore`, already per-asset), and `passes_gate`/`effective_score` gating in `signals.py` work unchanged. A one-off backtest script decides the `direction_rule` config before the live scheduler job starts emitting real claims.

**Tech Stack:** Python 3.12, SQLAlchemy, pytest, existing Argus app (FastAPI + APScheduler), Docker Compose deploy to Oracle VPS.

## Global Constraints

- Zero new DB tables — reuse `Claim`, `ClaimAudit`, `Source`, `SourceAssetScore` exactly as they exist today.
- Gate on `SourceAssetScore(source_id, asset, horizon)`, never the global `SourceScore` — this is the whole point of avoiding BTC/ETH score mixing (spec "Korekta po code review", pkt 6).
- `entry_price`/`entry_ts` for any cascade claim = price at `window_end`, never `window_start` or "now" at detection time — look-ahead bias fix (spec pkt 8). The same rule applies identically in the backtest script and in live emission, using the same `get_historical_price` call, so live behavior and backtest behavior are provably consistent.
- `min_events_required = 25` in the backtest — any (window, threshold, asset) combination with fewer detected cascades reports `"insufficient_data"` and must not be used to pick a `direction_rule`.
- No new third-party dependencies (no numpy/pandas) — `statistics` stdlib module covers everything needed.
- Confidence is never hardcoded to 0.5 — always `clamp(0.3 + cascade_strength * 0.4, 0.3, 0.9)` where `cascade_strength = total_notional / notional_p95`.
- Follow existing code style: no type hints beyond what's already used in `argus/`, `logging.getLogger(__name__)` per module, jobs in `main.py` wrapped in `try/except` that log and continue.

---

## Task 1: `CascadeEvent` dataclass + `detect_cascades` (pure, no DB/network)

**Files:**
- Create: `argus/argus/liquidations/cascade.py`
- Test: `argus/tests/test_cascade.py`

**Interfaces:**
- Consumes: nothing from other tasks (first task).
- Produces:
  - `CascadeEvent` dataclass: `asset: str`, `side: str`, `window_start: datetime`, `window_end: datetime`, `total_notional: float`, `n_fills: int`, `cascade_intensity: float`, `price_change_window: float | None` (default `None`).
  - `detect_cascades(liquidations: list, window_minutes: int, min_notional: float) -> list[CascadeEvent]` — used by Task 2, Task 3, Task 5.

**Design note (deviates from spec's literal wording, same outcome):** the spec describes "sliding windows" with a `merge_overlap_pct` to avoid spam from overlapping windows on one squeeze (review pkt 3). A simpler approach that achieves the identical goal: **gap-based clustering**. Sort fills by `ts` within each `(asset, side)` group; a new fill joins the current cluster if it's within `window_minutes` of the cluster's last fill (extending the cluster), otherwise it starts a new cluster. This produces exactly one cascade per contiguous burst — no overlapping windows are ever created, so there's nothing to merge. Simpler code, same result.

- [ ] **Step 1: Write the failing tests**

```python
# argus/tests/test_cascade.py
from datetime import datetime, timedelta, timezone
from argus.liquidations.cascade import CascadeEvent, detect_cascades


def _liq(asset="BTC", side="long_liq", notional=10000.0, minutes_offset=0):
    class _Row:
        pass
    r = _Row()
    r.asset = asset
    r.side = side
    r.notional_usd = notional
    r.ts = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes_offset)
    return r


def test_empty_input_returns_no_cascades():
    assert detect_cascades([], window_minutes=30, min_notional=50000) == []


def test_single_fill_below_threshold_is_not_a_cascade():
    liqs = [_liq(notional=1000.0)]
    assert detect_cascades(liqs, window_minutes=30, min_notional=50000) == []


def test_fills_within_window_cluster_into_one_cascade():
    liqs = [
        _liq(notional=20000.0, minutes_offset=0),
        _liq(notional=20000.0, minutes_offset=10),
        _liq(notional=20000.0, minutes_offset=20),
    ]
    result = detect_cascades(liqs, window_minutes=30, min_notional=50000)
    assert len(result) == 1
    c = result[0]
    assert c.asset == "BTC"
    assert c.side == "long_liq"
    assert c.total_notional == 60000.0
    assert c.n_fills == 3
    assert c.window_start == datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    assert c.window_end == datetime(2026, 1, 1, 10, 20, tzinfo=timezone.utc)


def test_gap_beyond_window_starts_new_cluster_no_overlap_spam():
    liqs = [
        _liq(notional=30000.0, minutes_offset=0),
        _liq(notional=30000.0, minutes_offset=10),
        _liq(notional=30000.0, minutes_offset=200),  # far beyond 30min window
        _liq(notional=30000.0, minutes_offset=210),
    ]
    result = detect_cascades(liqs, window_minutes=30, min_notional=50000)
    assert len(result) == 2
    assert result[0].total_notional == 60000.0
    assert result[1].total_notional == 60000.0


def test_different_asset_and_side_tracked_independently():
    liqs = [
        _liq(asset="BTC", side="long_liq", notional=60000.0, minutes_offset=0),
        _liq(asset="BTC", side="short_liq", notional=60000.0, minutes_offset=0),
        _liq(asset="ETH", side="long_liq", notional=60000.0, minutes_offset=0),
    ]
    result = detect_cascades(liqs, window_minutes=30, min_notional=50000)
    keys = {(c.asset, c.side) for c in result}
    assert keys == {("BTC", "long_liq"), ("BTC", "short_liq"), ("ETH", "long_liq")}


def test_cascade_intensity_is_notional_over_duration_minutes():
    liqs = [
        _liq(notional=30000.0, minutes_offset=0),
        _liq(notional=30000.0, minutes_offset=20),
    ]
    result = detect_cascades(liqs, window_minutes=30, min_notional=50000)
    assert len(result) == 1
    assert result[0].cascade_intensity == 60000.0 / 20


def test_single_fill_cascade_intensity_uses_minimum_duration_floor():
    liqs = [_liq(notional=60000.0, minutes_offset=0)]
    result = detect_cascades(liqs, window_minutes=30, min_notional=50000)
    assert len(result) == 1
    # duration floor of 1 minute avoids division by zero
    assert result[0].cascade_intensity == 60000.0 / 1.0


def test_price_change_window_defaults_to_none():
    liqs = [_liq(notional=60000.0)]
    result = detect_cascades(liqs, window_minutes=30, min_notional=50000)
    assert result[0].price_change_window is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd argus && MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd):/app" -w /app python:3.12-slim sh -c "pip install -q --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt && python -m pytest tests/test_cascade.py -v"`
Expected: FAIL with `ModuleNotFoundError: No module named 'argus.liquidations.cascade'`

- [ ] **Step 3: Write minimal implementation**

```python
# argus/argus/liquidations/cascade.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd argus && MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd):/app" -w /app python:3.12-slim sh -c "pip install -q --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt && python -m pytest tests/test_cascade.py -v"`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add argus/argus/liquidations/cascade.py argus/tests/test_cascade.py
git commit -m "feat(argus): add liquidation cascade detection (gap-based clustering)"
```

---

## Task 2: `annotate_price_context`, `compute_notional_p95`, `load_direction_rules`, `emit_cascade_claims`

**Files:**
- Modify: `argus/argus/liquidations/cascade.py` (append)
- Create: `argus/config/liq_cascade_rules.yaml`
- Modify: `argus/tests/test_cascade.py` (append)

**Interfaces:**
- Consumes: `CascadeEvent` from Task 1; `argus.models.{Asset, Claim, ClaimAudit, Source, Liquidation}`; `argus.prices.get_historical_price(asset, when) -> float` (raises on failure); `argus.db.SessionLocal` pattern used elsewhere in the codebase.
- Produces:
  - `annotate_price_context(session, cascades: list[CascadeEvent], lookback_minutes: int = 15) -> None` — mutates `cascade.price_change_window` in place. Used by Task 3, Task 5.
  - `compute_notional_p95(session) -> float` — used by Task 3, Task 5.
  - `load_direction_rules(path: str = "config/liq_cascade_rules.yaml") -> dict[str, str]` — used by Task 3, Task 5, Task 6.
  - `ensure_cascade_source(session) -> Source` — used by Task 4 (signals.py needs to look up the same `handle="liq-cascade"`).
  - `emit_cascade_claims(session, cascades: list[CascadeEvent], direction_rule: dict[str, str], notional_p95: float) -> int` — used by Task 3.

**Design note on `notional_p95`:** the spec says "rolling 30d p95". With only ~600 historical fills spread over 7 months, a strict rolling 30-day window can have zero or near-zero rows at many points in time, making the percentile undefined or noisy. This implementation uses **all-time** `notional_usd` history instead of a rolling window — same purpose (a stable reference point for "how big is this cascade relative to normal"), more robust given the actual data volume. Documented here and in a code comment; revisit if/when liquidation volume grows enough for a rolling window to be statistically meaningful.

- [ ] **Step 1: Write the failing tests**

```python
# append to argus/tests/test_cascade.py
from unittest.mock import patch
from argus.liquidations.cascade import (
    annotate_price_context, compute_notional_p95, load_direction_rules,
    ensure_cascade_source, emit_cascade_claims,
)
from argus.models import Asset, Liquidation, Source, Claim, ClaimAudit


def _cascade(asset="BTC", side="long_liq", notional=60000.0, start_offset=0, end_offset=20):
    start = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc) + timedelta(minutes=start_offset)
    end = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc) + timedelta(minutes=end_offset)
    return CascadeEvent(asset=asset, side=side, window_start=start, window_end=end,
                         total_notional=notional, n_fills=2,
                         cascade_intensity=notional / max((end - start).total_seconds() / 60, 1.0))


def test_annotate_price_context_computes_pct_change(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True, binance_symbol="BTCUSDT"))
    session.commit()
    cascades = [_cascade()]
    with patch("argus.liquidations.cascade.get_historical_price", side_effect=[100.0, 110.0]):
        annotate_price_context(session, cascades, lookback_minutes=15)
    assert cascades[0].price_change_window == pytest.approx((110.0 - 100.0) / 100.0)


def test_annotate_price_context_leaves_none_on_price_failure(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True, binance_symbol="BTCUSDT"))
    session.commit()
    cascades = [_cascade()]
    with patch("argus.liquidations.cascade.get_historical_price", side_effect=ValueError("no data")):
        annotate_price_context(session, cascades, lookback_minutes=15)
    assert cascades[0].price_change_window is None


def test_compute_notional_p95_uses_all_history(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True))
    session.commit()
    for n in [100.0, 200.0, 300.0, 400.0, 100000.0]:
        session.add(Liquidation(asset="BTC", exchange="hyperliquid", side="long_liq",
                                 price=1.0, qty=1.0, notional_usd=n,
                                 ts=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc)))
    session.commit()
    p95 = compute_notional_p95(session)
    assert p95 > 400.0  # dominated by the 100000 outlier, not just the median cluster


def test_compute_notional_p95_empty_table_returns_zero(session):
    assert compute_notional_p95(session) == 0.0


def test_load_direction_rules_missing_file_returns_empty_dict(tmp_path):
    missing = tmp_path / "does_not_exist.yaml"
    assert load_direction_rules(str(missing)) == {}


def test_load_direction_rules_reads_yaml(tmp_path):
    f = tmp_path / "rules.yaml"
    f.write_text("direction_rule:\n  BTC: continuation\n  ETH: contrarian\n")
    assert load_direction_rules(str(f)) == {"BTC": "continuation", "ETH": "contrarian"}


def test_ensure_cascade_source_creates_once(session):
    s1 = ensure_cascade_source(session)
    s2 = ensure_cascade_source(session)
    assert s1.id == s2.id
    assert s1.kind == "derived"
    assert s1.handle == "liq-cascade"


def test_emit_cascade_claims_skips_asset_without_rule(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True, binance_symbol="BTCUSDT"))
    session.commit()
    n = emit_cascade_claims(session, [_cascade()], direction_rule={}, notional_p95=10000.0)
    assert n == 0
    assert session.query(Claim).count() == 0


def test_emit_cascade_claims_contrarian_long_liq_means_bull(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True, binance_symbol="BTCUSDT"))
    session.commit()
    with patch("argus.liquidations.cascade.get_historical_price", return_value=50000.0):
        n = emit_cascade_claims(session, [_cascade(side="long_liq")],
                                 direction_rule={"BTC": "contrarian"}, notional_p95=10000.0)
    assert n == 1
    claim = session.query(Claim).one()
    assert claim.direction == "bull"
    assert claim.entry_price == 50000.0


def test_emit_cascade_claims_continuation_long_liq_means_bear(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True, binance_symbol="BTCUSDT"))
    session.commit()
    with patch("argus.liquidations.cascade.get_historical_price", return_value=50000.0):
        n = emit_cascade_claims(session, [_cascade(side="long_liq")],
                                 direction_rule={"BTC": "continuation"}, notional_p95=10000.0)
    claim = session.query(Claim).one()
    assert claim.direction == "bear"


def test_emit_cascade_claims_entry_ts_is_window_end_not_window_start(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True, binance_symbol="BTCUSDT"))
    session.commit()
    cascade = _cascade(start_offset=0, end_offset=20)
    with patch("argus.liquidations.cascade.get_historical_price", return_value=50000.0):
        emit_cascade_claims(session, [cascade], direction_rule={"BTC": "contrarian"}, notional_p95=10000.0)
    claim = session.query(Claim).one()
    assert claim.entry_ts == cascade.window_end
    assert claim.entry_ts != cascade.window_start


def test_emit_cascade_claims_confidence_scales_with_cascade_size(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True, binance_symbol="BTCUSDT"))
    session.commit()
    small = _cascade(notional=1000.0)
    huge = _cascade(notional=1000000.0)
    with patch("argus.liquidations.cascade.get_historical_price", return_value=50000.0):
        emit_cascade_claims(session, [small], direction_rule={"BTC": "contrarian"}, notional_p95=10000.0)
        small_conf = session.query(Claim).one().confidence
        emit_cascade_claims(session, [huge], direction_rule={"BTC": "contrarian"}, notional_p95=10000.0)
    confs = sorted(c.confidence for c in session.query(Claim).all())
    assert confs[0] == pytest.approx(small_conf)
    assert confs[-1] > confs[0]
    assert 0.3 <= confs[0] <= 0.9
    assert 0.3 <= confs[-1] <= 0.9


def test_emit_cascade_claims_dedups_same_window(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True, binance_symbol="BTCUSDT"))
    session.commit()
    cascade = _cascade()
    with patch("argus.liquidations.cascade.get_historical_price", return_value=50000.0):
        n1 = emit_cascade_claims(session, [cascade], direction_rule={"BTC": "contrarian"}, notional_p95=10000.0)
        n2 = emit_cascade_claims(session, [cascade], direction_rule={"BTC": "contrarian"}, notional_p95=10000.0)
    assert n1 == 1
    assert n2 == 0
    assert session.query(Claim).count() == 1


def test_emit_cascade_claims_skips_on_price_failure(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True, binance_symbol="BTCUSDT"))
    session.commit()
    with patch("argus.liquidations.cascade.get_historical_price", side_effect=ValueError("no data")):
        n = emit_cascade_claims(session, [_cascade()], direction_rule={"BTC": "contrarian"}, notional_p95=10000.0)
    assert n == 0
    assert session.query(Claim).count() == 0
```

Add `import pytest` at the top of `test_cascade.py` if not already present (needed for `pytest.approx`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd argus && MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd):/app" -w /app python:3.12-slim sh -c "pip install -q --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt && python -m pytest tests/test_cascade.py -v"`
Expected: FAIL — `ImportError: cannot import name 'annotate_price_context'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to argus/argus/liquidations/cascade.py
import os
from datetime import timezone
import yaml
from sqlalchemy import select

from argus.models import Asset, Claim, ClaimAudit, Liquidation, Source
from argus.prices import get_historical_price


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
    values = sorted(session.scalars(select(Liquidation.notional_usd)))
    if not values:
        return 0.0
    idx = max(0, int(0.95 * len(values)) - 1)
    return values[min(idx, len(values) - 1)]


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
        raw_key = f"LIQ_CASCADE:{cascade.asset}:{cascade.side}:{cascade.window_start.isoformat()}"
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
```

Create `argus/config/liq_cascade_rules.yaml`:

```yaml
# Direction rule per asset, decided by docs/superpowers/plans backtest (Task 6).
# "contrarian": long_liq cascade -> bull, short_liq cascade -> bear
# "continuation": long_liq cascade -> bear, short_liq cascade -> bull
# An asset with no entry here gets NO claims emitted (insufficient backtest data) — see Task 6.
direction_rule: {}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd argus && MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd):/app" -w /app python:3.12-slim sh -c "pip install -q --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt && python -m pytest tests/test_cascade.py -v"`
Expected: all tests in the file pass (8 from Task 1 + 13 new = 21 passed)

- [ ] **Step 5: Commit**

```bash
git add argus/argus/liquidations/cascade.py argus/config/liq_cascade_rules.yaml argus/tests/test_cascade.py
git commit -m "feat(argus): emit liquidation cascade claims via synthetic derived source"
```

---

## Task 3: Scheduler job `_liq_cascade_job`

**Files:**
- Modify: `argus/argus/main.py`

**Interfaces:**
- Consumes: `detect_cascades`, `annotate_price_context`, `compute_notional_p95`, `load_direction_rules`, `emit_cascade_claims` from Task 1/2; `argus.models.Liquidation`.
- Produces: nothing new consumed by later tasks — this is the wiring task. (Task 4 is independent of this one; Task 6 deploys both.)

No test file for this task — consistent with the existing codebase convention: `_rss_job`, `_hyperliquid_job`, `_insider_job`, etc. in `main.py` have no dedicated unit tests; only the functions they call do (already covered in Task 1/2). Verified by checking `argus/tests/` has no `test_main.py`.

- [ ] **Step 1: Add the job function**

In `argus/argus/main.py`, add `timedelta` to the existing datetime import on line 16:

```python
from datetime import datetime, timedelta, timezone
```

Add this function after `_hyperliquid_job` (after line 54, before `def _insider_job`):

```python
def _liq_cascade_job():
    from argus.liquidations.cascade import (
        detect_cascades, annotate_price_context, compute_notional_p95,
        load_direction_rules, emit_cascade_claims,
    )
    from argus.models import Liquidation
    import logging
    window_minutes = int(os.getenv("ARGUS_LIQ_CASCADE_WINDOW_MIN", "30"))
    min_notional = float(os.getenv("ARGUS_LIQ_CASCADE_MIN_NOTIONAL", "50000"))
    lookback = timedelta(minutes=window_minutes * 2 + 60)
    try:
        with SessionLocal() as s:
            cutoff = datetime.now(timezone.utc) - lookback
            liqs = list(s.scalars(
                select(Liquidation).where(Liquidation.ts >= cutoff).order_by(Liquidation.ts)
            ))
            cascades = detect_cascades(liqs, window_minutes, min_notional)
            if not cascades:
                return
            annotate_price_context(s, cascades)
            rules = load_direction_rules()
            p95 = compute_notional_p95(s)
            n = emit_cascade_claims(s, cascades, rules, p95)
            logging.getLogger(__name__).info(
                "liq_cascade: detected %d cascades, emitted %d claims", len(cascades), n
            )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("liq_cascade job failed: %s", e)
```

- [ ] **Step 2: Register the job in `bootstrap()`**

In `argus/argus/main.py`, add this line after line 174 (`sched.add_interval("signal_outcomes", ...)`):

```python
    sched.add_interval("liq_cascade", _liq_cascade_job, minutes=30)
```

- [ ] **Step 3: Verify the module still imports cleanly**

Run: `cd argus && MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd):/app" -w /app python:3.12-slim sh -c "pip install -q --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt && python -c 'import argus.main'"`
Expected: no output, exit code 0 (import succeeds)

- [ ] **Step 4: Run the full test suite to confirm no regressions**

Run: `cd argus && MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd):/app" -w /app python:3.12-slim sh -c "pip install -q --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt && python -m pytest tests/ -q"`
Expected: same pass/fail counts as before this task (228+21 passed / 9 pre-existing failures unrelated to this change — verify the 9 failures are the same ones listed in `docs`/memory, not new ones)

- [ ] **Step 5: Commit**

```bash
git add argus/argus/main.py
git commit -m "feat(argus): wire liquidation cascade detection into scheduler"
```

---

## Task 4: `signals.py::check_liquidation_signals` (new Tier 3, gated on `SourceAssetScore`)

**Files:**
- Modify: `argus/argus/signals.py`
- Modify: `argus/tests/test_signals.py`

**Interfaces:**
- Consumes: `Claim`, `Source`, `SourceAssetScore`, `Asset` models directly. Does **not** call `ensure_cascade_source` from Task 2 — `check_liquidation_signals` only reads (`session.scalar(select(Source).where(...))`, returns `[]` if the source doesn't exist yet); it must never create a source as a side effect of checking for signals, since the cron job (Task 3) is the only thing that should ever create the `liq-cascade` source.
- Produces: `check_liquidation_signals(session) -> list[SignalResult]`, wired into `send_signals`. `format_signal_message` extended for `tier == "liq_cascade"`.

- [ ] **Step 1: Write the failing tests**

```python
# append to argus/tests/test_signals.py
from argus.models import SourceAssetScore
from argus.signals import check_liquidation_signals


def _cascade_source(session):
    src = Source(kind="derived", handle="liq-cascade", display_name="Liquidation Cascade", active=True)
    session.add(src)
    session.commit()
    return src


def _asset_score(session, source_id, asset, decayed_score, n_claims, hit_rate=0.7, horizon="24h"):
    session.add(SourceAssetScore(source_id=source_id, asset=asset, horizon=horizon,
                                  n_claims=n_claims, n_hits=int(n_claims * hit_rate),
                                  hit_rate=hit_rate, avg_return=0.02, decayed_score=decayed_score,
                                  updated_at=datetime.now(timezone.utc)))
    session.commit()


def test_liquidation_signal_fires_when_gate_passes(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True))
    session.commit()
    src = _cascade_source(session)
    _asset_score(session, src.id, "BTC", decayed_score=0.70, n_claims=6)
    session.add(Claim(source_id=src.id, asset="BTC", direction="bull", confidence=0.6,
                       method="rule", entry_price=50000.0, entry_ts=datetime.now(timezone.utc),
                       status="open"))
    session.commit()
    results = check_liquidation_signals(session)
    assert len(results) == 1
    assert results[0].tier == "liq_cascade"
    assert results[0].asset == "BTC"
    assert results[0].direction == "bull"


def test_liquidation_signal_blocked_when_gate_fails(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True))
    session.commit()
    src = _cascade_source(session)
    _asset_score(session, src.id, "BTC", decayed_score=0.40, n_claims=6)  # below 0.60 gate
    session.add(Claim(source_id=src.id, asset="BTC", direction="bull", confidence=0.6,
                       method="rule", entry_price=50000.0, entry_ts=datetime.now(timezone.utc),
                       status="open"))
    session.commit()
    assert check_liquidation_signals(session) == []


def test_liquidation_signal_ignores_stale_claims(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True))
    session.commit()
    src = _cascade_source(session)
    _asset_score(session, src.id, "BTC", decayed_score=0.70, n_claims=6)
    old_ts = datetime.now(timezone.utc) - timedelta(hours=5)
    session.add(Claim(source_id=src.id, asset="BTC", direction="bull", confidence=0.6,
                       method="rule", entry_price=50000.0, entry_ts=old_ts, status="open"))
    session.commit()
    assert check_liquidation_signals(session) == []


def test_liquidation_signal_uses_per_asset_score_not_mixed(session):
    """The key regression test for the SourceAssetScore fix: a great BTC score and a
    terrible ETH score on the SAME source must not bleed into each other."""
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True))
    session.add(Asset(symbol="ETH", kind="crypto", scorable=True))
    session.commit()
    src = _cascade_source(session)
    _asset_score(session, src.id, "BTC", decayed_score=0.80, n_claims=10)  # passes gate
    _asset_score(session, src.id, "ETH", decayed_score=0.20, n_claims=10)  # fails gate
    now = datetime.now(timezone.utc)
    session.add(Claim(source_id=src.id, asset="BTC", direction="bull", confidence=0.6,
                       method="rule", entry_price=50000.0, entry_ts=now, status="open"))
    session.add(Claim(source_id=src.id, asset="ETH", direction="bear", confidence=0.6,
                       method="rule", entry_price=3000.0, entry_ts=now, status="open"))
    session.commit()
    results = check_liquidation_signals(session)
    assert len(results) == 1
    assert results[0].asset == "BTC"


def test_liquidation_signal_respects_cooldown(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True))
    session.commit()
    src = _cascade_source(session)
    _asset_score(session, src.id, "BTC", decayed_score=0.70, n_claims=6)
    session.add(Claim(source_id=src.id, asset="BTC", direction="bull", confidence=0.6,
                       method="rule", entry_price=50000.0, entry_ts=datetime.now(timezone.utc),
                       status="open"))
    session.add(SignalLog(tier="liq_cascade", asset="BTC", direction="bull",
                          source_ids="[]", signal_strength=0.5, entry_price=50000.0,
                          stop_price=47500.0, position_pct=0.03,
                          sent_at=datetime.now(timezone.utc)))
    session.commit()
    assert check_liquidation_signals(session) == []


def test_format_signal_message_handles_liq_cascade_tier():
    from argus.signals import format_signal_message, SignalResult
    result = SignalResult(tier="liq_cascade", asset="BTC", asset_kind="crypto", direction="bull",
                          source_ids=[1], source_labels=["Liquidation Cascade · 0.70 · 70%@24h · n=6"],
                          signal_strength=0.5, entry_price=50000.0, stop_price=47500.0,
                          position_pct=0.03, risk_pct=0.02, stop_pct=0.05, vol_tier="large",
                          horizon="24h", window_str=None, whale_notional=None)
    msg = format_signal_message(result)
    assert "LIQUIDATION CASCADE" in msg
    assert "BTC" in msg
```

Check the top of `argus/tests/test_signals.py` already imports `Source`, `SignalLog`, `datetime`, `timezone`, `timedelta` — add any missing ones (`SourceAssetScore`) to the existing import line from `argus.models`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd argus && MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd):/app" -w /app python:3.12-slim sh -c "pip install -q --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt && python -m pytest tests/test_signals.py -v -k liquidation"`
Expected: FAIL with `ImportError: cannot import name 'check_liquidation_signals'`

- [ ] **Step 3: Write minimal implementation**

In `argus/argus/signals.py`, change the import on line 8-11 to add `SourceAssetScore`:

```python
from argus.models import (
    Asset, Claim, Price, Source, SourceScore, SourceAssetScore,
    SignalLog, SignalOutcome, WalletPosition,
)
```

Add this function after `_get_source_score` (after line 116, before `_last_price`):

```python
def _get_source_asset_score(session, source_id: int, asset: str, horizon: str):
    return session.scalar(
        select(SourceAssetScore).where(
            SourceAssetScore.source_id == source_id,
            SourceAssetScore.asset == asset,
            SourceAssetScore.horizon == horizon,
        )
    )
```

Add this function after `check_whale_signals` (after line 194, before `check_confluence_signals`):

```python
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
        if ss is None or not passes_gate(ss.decayed_score, ss.n_claims):
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
```

Modify `send_signals` (lines 307-315) to:

```python
def send_signals(session) -> None:
    whale = check_whale_signals(session)
    confluence = check_confluence_signals(session)
    liq_cascade = check_liquidation_signals(session)
    for result in whale + confluence + liq_cascade:
        msg = format_signal_message(result)
        send_message(msg)
        _save_signal(session, result)
        logger.info("signal sent: %s %s %s strength=%.2f",
                    result.tier, result.direction, result.asset, result.signal_strength)
```

Modify `format_signal_message` (lines 318-323) to:

```python
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
```

(the rest of `format_signal_message` after line 324 stays unchanged).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd argus && MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd):/app" -w /app python:3.12-slim sh -c "pip install -q --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt && python -m pytest tests/test_signals.py -v"`
Expected: all tests pass, including the 6 new ones

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `cd argus && MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd):/app" -w /app python:3.12-slim sh -c "pip install -q --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt && python -m pytest tests/ -q"`
Expected: same pre-existing 9 failures, zero new ones

- [ ] **Step 6: Commit**

```bash
git add argus/argus/signals.py argus/tests/test_signals.py
git commit -m "feat(argus): add liq_cascade signal tier gated on per-asset SourceAssetScore"
```

---

## Task 5: Backtest script `scripts/backtest_liq_cascades.py`

**Files:**
- Create: `argus/scripts/backtest_liq_cascades.py`
- Create: `argus/scripts/__init__.py` (empty, makes it an importable package for `python -m`)

**Interfaces:**
- Consumes: `detect_cascades`, `annotate_price_context` from Task 1/2; `argus.prices.get_historical_price`; `argus.db.SessionLocal`; `argus.models.{Liquidation, Asset}`.
- Produces: a printed report only — nothing downstream consumes this programmatically. Task 6 reads its console output by hand to fill in `config/liq_cascade_rules.yaml`.

No automated tests for this file, per the approved spec ("one-off analysis tool"). Step 5 below is a manual smoke-test on a synthetic fixture instead of pytest, to catch obvious bugs before running against real VPS data.

- [ ] **Step 1: Write the script**

```python
# argus/scripts/__init__.py
```

```python
# argus/scripts/backtest_liq_cascades.py
"""
One-off backtest: decide the liquidation-cascade direction_rule (contrarian vs
continuation) per asset, using real historical `liquidations` + price data.
Not part of the live app — run manually, read the report, edit
config/liq_cascade_rules.yaml by hand based on the result.

Usage (inside the Argus container, where DATABASE_URL is already configured):
    python -m scripts.backtest_liq_cascades
"""
import statistics
from datetime import timedelta, timezone
from sqlalchemy import select

from argus.db import SessionLocal
from argus.models import Asset, Liquidation
from argus.liquidations.cascade import detect_cascades, annotate_price_context
from argus.prices import get_historical_price

WINDOW_CANDIDATES = [15, 30, 60]
NOTIONAL_CANDIDATES = [10_000, 25_000, 50_000, 100_000]
HORIZONS = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7)}
MIN_EVENTS_REQUIRED = 25

# review pkt 4: does requiring momentum INTO the liquidation (price already moving
# the way that would cause this side to get liquidated) change the hit rate vs no filter?
MOMENTUM_THRESHOLD = 0.01  # 1% move in the 15min before the cascade counts as "momentum present"


def _has_momentum(cascade) -> bool:
    if cascade.price_change_window is None:
        return False
    # long_liq cascades happen because price fell; short_liq because price rose
    if cascade.side == "long_liq":
        return cascade.price_change_window <= -MOMENTUM_THRESHOLD
    return cascade.price_change_window >= MOMENTUM_THRESHOLD


def _evaluate_cascade(asset_row, cascade, horizon_delta):
    entry = get_historical_price(asset_row, cascade.window_end)
    later = get_historical_price(asset_row, cascade.window_end + horizon_delta)
    ret = (later - entry) / entry
    # contrarian hypothesis: long_liq -> expect price UP (ret > 0); short_liq -> expect DOWN
    contrarian_hit = ret > 0 if cascade.side == "long_liq" else ret < 0
    continuation_hit = not contrarian_hit
    return ret, contrarian_hit, continuation_hit


def _report_row(label, asset_symbol, window_minutes, min_notional, horizon_name,
                 asset_row, cascades, horizon_delta):
    if len(cascades) < MIN_EVENTS_REQUIRED:
        print(f"{label:<10} {asset_symbol:<6} {window_minutes:>7} {min_notional:>13.0f} "
              f"{horizon_name:>8} {len(cascades):>5}  insufficient_data (need >= {MIN_EVENTS_REQUIRED})")
        return
    returns, contrarian_hits, continuation_hits = [], [], []
    for c in cascades:
        try:
            ret, c_hit, k_hit = _evaluate_cascade(asset_row, c, horizon_delta)
        except Exception as e:
            print(f"  skip {asset_symbol} {c.window_end}: {e}")
            continue
        returns.append(ret)
        contrarian_hits.append(c_hit)
        continuation_hits.append(k_hit)
    if not returns:
        return
    buy_hold = statistics.mean(returns)
    contrarian_rate = sum(contrarian_hits) / len(contrarian_hits)
    continuation_rate = sum(continuation_hits) / len(continuation_hits)
    print(f"{label:<10} {asset_symbol:<6} {window_minutes:>7} {min_notional:>13.0f} "
          f"{horizon_name:>8} {len(returns):>5} {0.50:>8.0%} {buy_hold:>10.2%} "
          f"{contrarian_rate:>11.0%} {continuation_rate:>13.0%}")


def run_backtest():
    with SessionLocal() as s:
        all_liqs = list(s.scalars(select(Liquidation).order_by(Liquidation.ts)))
        assets = {a.symbol: a for a in s.scalars(select(Asset))}

        print(f"Total liquidation rows: {len(all_liqs)}")
        print(f"{'variant':<10} {'asset':<6} {'window':>7} {'min_notional':>13} {'horizon':>8} "
              f"{'n':>5} {'random':>8} {'buy&hold':>10} {'contrarian':>11} {'continuation':>13}")

        for window_minutes in WINDOW_CANDIDATES:
            for min_notional in NOTIONAL_CANDIDATES:
                cascades = detect_cascades(all_liqs, window_minutes, min_notional)
                annotate_price_context(s, cascades)
                by_asset: dict[str, list] = {}
                for c in cascades:
                    by_asset.setdefault(c.asset, []).append(c)

                for asset_symbol, asset_cascades in by_asset.items():
                    asset_row = assets.get(asset_symbol)
                    if asset_row is None:
                        continue

                    # review pkt 5: cascade_intensity as an alternative threshold —
                    # keep only the top half by intensity within this bucket, see if
                    # that subset is more predictive than the raw notional threshold alone.
                    intensities = sorted(c.cascade_intensity for c in asset_cascades)
                    intensity_median = intensities[len(intensities) // 2]
                    high_intensity = [c for c in asset_cascades if c.cascade_intensity >= intensity_median]

                    # review pkt 4: momentum filter — only cascades where price was
                    # already moving the way that caused this side to get liquidated.
                    with_momentum = [c for c in asset_cascades if _has_momentum(c)]

                    for horizon_name, horizon_delta in HORIZONS.items():
                        _report_row("all", asset_symbol, window_minutes, min_notional,
                                    horizon_name, asset_row, asset_cascades, horizon_delta)
                        _report_row("intensity", asset_symbol, window_minutes, min_notional,
                                    horizon_name, asset_row, high_intensity, horizon_delta)
                        _report_row("momentum", asset_symbol, window_minutes, min_notional,
                                    horizon_name, asset_row, with_momentum, horizon_delta)


if __name__ == "__main__":
    run_backtest()
```

The report has three `variant` rows per `(asset, window, min_notional, horizon)`: `all` (every detected cascade, the baseline), `intensity` (top half by `cascade_intensity` — review pkt 5), `momentum` (only cascades with pre-existing momentum in the liquidated direction — review pkt 4). If `intensity` or `momentum` shows a meaningfully better hit rate than `all` for an asset, prefer that as a pre-filter when deciding `direction_rule` in Task 6 (note: the current `emit_cascade_claims` from Task 2 does not yet apply an intensity/momentum pre-filter live — if the backtest shows one is needed, that's a follow-up change to `emit_cascade_claims`, flagged in Task 6's final note, not silently added here).

- [ ] **Step 2: Smoke-test against a tiny synthetic fixture (not the real DB)**

Create a throwaway local check — run this inline with `docker run` to verify the script's internal logic (cascade detection + evaluation loop) doesn't crash, using a fake in-memory `SessionLocal` is overkill for a one-off script, so instead verify by reading: confirm `detect_cascades` signature matches Task 1's, confirm `get_historical_price` signature matches `argus/prices.py:39` (`get_historical_price(asset, when)`), confirm `Liquidation` columns (`asset`, `side`, `notional_usd`, `ts`) match `argus/models.py:117-132`.

Run: `cd argus && MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd):/app" -w /app python:3.12-slim python -c "import ast; ast.parse(open('scripts/backtest_liq_cascades.py').read())"`
Expected: no output, exit code 0 (confirms the file is syntactically valid Python before it ever touches the VPS)

- [ ] **Step 3: Commit**

```bash
git add argus/scripts/__init__.py argus/scripts/backtest_liq_cascades.py
git commit -m "feat(argus): add one-off liquidation cascade backtest script"
```

---

## Task 6: Run backtest on VPS, decide `direction_rule`, deploy, verify live

**Files:**
- Modify: `argus/config/liq_cascade_rules.yaml` (fill in real values from the backtest)
- No code changes beyond config — this task is backtest execution + deploy + smoke verification.

**Interfaces:**
- Consumes: everything from Tasks 1-5, already committed.
- Produces: a live, deployed feature. Terminal task of this plan.

- [ ] **Step 1: Run the full local test suite one more time before touching the VPS**

Run: `cd argus && MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd):/app" -w /app python:3.12-slim sh -c "pip install -q --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt && python -m pytest tests/ -q"`
Expected: same pre-existing 9 failures as the baseline noted in Task 3/4, zero new failures

- [ ] **Step 2: Deploy the new code to the VPS (without rules filled in yet — safe, emits zero claims)**

```bash
scp -i "C:\ai\ssh-key-2026-05-19.key" \
  argus/argus/liquidations/cascade.py \
  ubuntu@84.235.174.129:/tmp/cascade.py
scp -i "C:\ai\ssh-key-2026-05-19.key" \
  argus/argus/main.py \
  ubuntu@84.235.174.129:/tmp/main.py
scp -i "C:\ai\ssh-key-2026-05-19.key" \
  argus/argus/signals.py \
  ubuntu@84.235.174.129:/tmp/signals.py
scp -i "C:\ai\ssh-key-2026-05-19.key" \
  argus/config/liq_cascade_rules.yaml \
  ubuntu@84.235.174.129:/tmp/liq_cascade_rules.yaml
scp -i "C:\ai\ssh-key-2026-05-19.key" -r \
  argus/scripts \
  ubuntu@84.235.174.129:/tmp/scripts
ssh -i "C:\ai\ssh-key-2026-05-19.key" ubuntu@84.235.174.129 "
  cp /tmp/cascade.py ~/argus/argus/liquidations/cascade.py &&
  cp /tmp/main.py ~/argus/argus/main.py &&
  cp /tmp/signals.py ~/argus/argus/signals.py &&
  cp /tmp/liq_cascade_rules.yaml ~/argus/config/liq_cascade_rules.yaml &&
  cp -r /tmp/scripts ~/argus/scripts
"
```

- [ ] **Step 3: Run the backtest on the VPS against real data**

```bash
ssh -i "C:\ai\ssh-key-2026-05-19.key" ubuntu@84.235.174.129 "cd ~/argus && docker compose run --rm app python -m scripts.backtest_liq_cascades"
```

Read the printed table. For each `(asset, window, min_notional, horizon)` row with `n >= 25`: compare `contrarian` and `continuation` rates against the `buy&hold` baseline and `random=50%`. A rule is worth adopting for an asset only if one hypothesis clears both benchmarks by a noticeable margin (a few points isn't enough at n=25-100 — use judgment, but don't adopt a rule that's within noise of 50%/buy-and-hold). If multiple `(window, min_notional)` configs agree on the same winning hypothesis for an asset, that's a stronger signal than a single config.

- [ ] **Step 4: Edit `config/liq_cascade_rules.yaml` based on the report**

Edit the local file `argus/config/liq_cascade_rules.yaml` (not the VPS copy directly — the VPS copy gets overwritten on the next deploy anyway). Example shape if BTC showed a clear contrarian edge and ETH showed insufficient data or no edge:

```yaml
direction_rule:
  BTC: contrarian
```

If no asset clears the bar, leave `direction_rule: {}` — this is a legitimate outcome ("417-600 historical events isn't enough to find a real edge yet, keep collecting") and the feature stays deployed-but-silent until more cascades accumulate and a future re-run of the backtest finds something.

- [ ] **Step 5: Deploy the final config and rebuild**

```bash
scp -i "C:\ai\ssh-key-2026-05-19.key" \
  argus/config/liq_cascade_rules.yaml \
  ubuntu@84.235.174.129:/tmp/liq_cascade_rules.yaml
ssh -i "C:\ai\ssh-key-2026-05-19.key" ubuntu@84.235.174.129 "
  cp /tmp/liq_cascade_rules.yaml ~/argus/config/liq_cascade_rules.yaml &&
  cd ~/argus &&
  docker compose build app &&
  docker compose up -d app
"
```

- [ ] **Step 6: Verify the live code matches what was deployed**

```bash
ssh -i "C:\ai\ssh-key-2026-05-19.key" ubuntu@84.235.174.129 "docker compose -f ~/argus/docker-compose.yml exec app python -c \"import inspect; from argus.liquidations import cascade; print(inspect.getsource(cascade.emit_cascade_claims))\" | head -5"
```
Expected: prints the function signature line `def emit_cascade_claims(session, cascades: list[CascadeEvent], direction_rule: dict[str, str],` confirming the live container has the new code, not a stale image (known deploy pitfall — `docker compose build` must run before `up -d`, scp alone is not enough).

- [ ] **Step 7: Run the test suite inside the live container**

```bash
ssh -i "C:\ai\ssh-key-2026-05-19.key" ubuntu@84.235.174.129 "cd ~/argus && docker compose run --rm -v ~/argus/tests:/app/tests -e PYTHONPATH=/app app pytest tests/test_cascade.py tests/test_signals.py -v"
```
Expected: all new tests pass in the production container, not just locally

- [ ] **Step 8: Wait for one scheduler cycle (up to 30 min) and check for activity**

```bash
ssh -i "C:\ai\ssh-key-2026-05-19.key" ubuntu@84.235.174.129 "docker logs argus-app --since 35m 2>&1 | grep liq_cascade"
```
Expected: a log line `liq_cascade: detected N cascades, emitted M claims` (M may legitimately be 0 if `direction_rule` is empty or no fresh cascades occurred in the lookback window — that's correct behavior, not a failure)

- [ ] **Step 9: Confirm claims appear in the DB if `direction_rule` had entries**

```bash
ssh -i "C:\ai\ssh-key-2026-05-19.key" ubuntu@84.235.174.129 "cd ~/argus && docker compose exec -T db psql -U argus -d argus -c \"SELECT c.asset, c.direction, c.confidence, c.entry_ts FROM claims c JOIN sources s ON c.source_id = s.id WHERE s.handle = 'liq-cascade' ORDER BY c.entry_ts DESC LIMIT 10;\""
```

- [ ] **Step 10: Commit the final rules config**

```bash
git add argus/config/liq_cascade_rules.yaml
git commit -m "feat(argus): set liquidation cascade direction_rule from backtest results"
```

**Note for whoever continues this work:**
- Outcomes for these claims mature over 1h/24h/7d like every other source — `SourceAssetScore` for `liq-cascade` won't be meaningful until the existing `_score_job` (runs every 6h) has had several days of fresh claims to evaluate. Check `/api/sources?asset=BTC` (or query `source_asset_scores` directly) after about a week to see whether the chosen `direction_rule` is holding up on live data, not just the backtest.
- If the backtest's `intensity` or `momentum` variant rows (Task 5) showed a meaningfully better hit rate than the `all` baseline for an asset that made it into `direction_rule`, that's a real follow-up: `emit_cascade_claims` (Task 2) currently emits a claim for every cascade that clears `min_notional`, with no intensity/momentum pre-filter. Adding one would mean threading `cascade_intensity`/`price_change_window` thresholds into `emit_cascade_claims` the same way `min_notional` already works — a small, well-scoped follow-up task, not done here because it depends on what this backtest actually finds.
