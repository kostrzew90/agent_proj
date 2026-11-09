# Argus Signal Notifier — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Argus wysyła Telegramem alerty inwestycyjne (whale moves + confluence) z rekomendacją pozycji opartą na nauczonych scorach źródeł.

**Architecture:** Dwa nowe pliki (`telegram.py`, `signals.py`) + dwie nowe tabele DB (`signal_log`, `signal_outcomes`) + trzy nowe jopy w schedulerze. Czyste funkcje w signals.py testowane bez DB; funkcje DB testowane przez istniejący SQLite fixture.

**Tech Stack:** Python 3.12, SQLAlchemy (Mapped), APScheduler, httpx (Telegram), istniejący `SessionLocal` / `TZDateTime` / `Base` pattern.

---

## File Structure

| Plik | Akcja | Odpowiedzialność |
|---|---|---|
| `argus/telegram.py` | CREATE | send_message() do Telegram Bot API |
| `argus/signals.py` | CREATE | scoring functions, check_whale, check_confluence, format, evaluate_outcomes |
| `argus/models.py` | MODIFY | dodaj SignalLog + SignalOutcome modele |
| `argus/main.py` | MODIFY | dodaj 3 jopy do schedulera |
| `tests/test_signals.py` | CREATE | testy jednostkowe i integracyjne |

---

## Istniejące wzorce (czytaj przed implementacją)

- **Session pattern:** `with SessionLocal() as s:` — patrz `main.py`
- **Model pattern:** `Mapped[str]`, `TZDateTime()`, `UniqueConstraint` — patrz `models.py`
- **Telegram pattern:** `guardian/telegram.py` — POST do `sendMessage`, swallow errors
- **Test session fixture:** `tests/conftest.py` — SQLite in-memory, fixture `session`
- **Job pattern:** funkcja `_xxx_job()` bez parametrów, `sched.add_interval("name", fn, minutes=N)` — patrz `main.py`
- **Import guard w jobach:** `from argus.xxx import yyy` wewnątrz funkcji (lazy import) — patrz `_llm_batch_job`

Nie ma `yf_symbol` dla krypto — `get_spot_price(asset)` używa `binance_symbol` dla crypto, `yf_symbol` dla stock. Nie wywołuj `get_spot_price` dla asset bez odpowiedniego pola.

---

## Task 1: argus/telegram.py

**Files:**
- Create: `argus/telegram.py`
- Test: `tests/test_signals.py` (sekcja telegram)

- [ ] **Step 1: Write failing test**

```python
# tests/test_signals.py
from unittest.mock import patch, MagicMock

def test_send_message_posts_to_telegram():
    with patch("httpx.post") as mock_post:
        import importlib, sys
        # reload so env vars take effect
        env = {"TELEGRAM_BOT_TOKEN": "tok123", "TELEGRAM_CHAT_ID": "chat456"}
        with patch.dict("os.environ", env):
            if "argus.telegram" in sys.modules:
                del sys.modules["argus.telegram"]
            from argus.telegram import send_message
            send_message("hello")
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "tok123" in call_kwargs.args[0]
        assert call_kwargs.kwargs["json"]["text"] == "hello"

def test_send_message_silent_when_no_token():
    with patch("httpx.post") as mock_post:
        with patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}):
            import sys
            if "argus.telegram" in sys.modules:
                del sys.modules["argus.telegram"]
            from argus.telegram import send_message
            send_message("hello")
        mock_post.assert_not_called()

def test_send_message_swallows_network_error():
    import httpx
    with patch("httpx.post", side_effect=httpx.ConnectError("fail")):
        with patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_CHAT_ID": "chat"}):
            import sys
            if "argus.telegram" in sys.modules:
                del sys.modules["argus.telegram"]
            from argus.telegram import send_message
            send_message("hello")  # must not raise
```

- [ ] **Step 2: Run test — verify FAIL**

```
docker compose run --rm -v ~/argus/tests:/app/tests -e PYTHONPATH=/app app pytest tests/test_signals.py::test_send_message_posts_to_telegram -v
```

Expected: `ImportError` or `ModuleNotFoundError` (argus.telegram doesn't exist yet).

- [ ] **Step 3: Implement argus/telegram.py**

```python
import os
import httpx

_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")


def send_message(text: str) -> None:
    if not _TOKEN or not _CHAT:
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{_TOKEN}/sendMessage",
            json={"chat_id": _CHAT, "text": text},
            timeout=10,
        )
    except Exception:
        pass
```

- [ ] **Step 4: Run tests — verify PASS**

```
docker compose run --rm -v ~/argus/tests:/app/tests -e PYTHONPATH=/app app pytest tests/test_signals.py -k "telegram" -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add argus/telegram.py tests/test_signals.py
git commit -m "feat(signals): argus/telegram.py send_message"
```

---

## Task 2: Models — SignalLog + SignalOutcome

**Files:**
- Modify: `argus/models.py` (append at end)
- Test: `tests/test_signals.py`

- [ ] **Step 1: Write failing tests**

Dodaj do `tests/test_signals.py`:

```python
from argus.models import SignalLog, SignalOutcome

def test_signal_log_persists(session):
    from datetime import datetime, timezone
    log = SignalLog(
        tier="whale",
        asset="BTC",
        direction="bull",
        source_ids='[1]',
        signal_strength=0.55,
        entry_price=67400.0,
        stop_price=64030.0,
        position_pct=0.20,
        sent_at=datetime.now(timezone.utc),
    )
    session.add(log)
    session.commit()
    assert log.id is not None

def test_signal_outcome_links_to_log(session):
    from datetime import datetime, timezone
    log = SignalLog(
        tier="confluence", asset="ETH", direction="bull",
        source_ids='[1,2]', signal_strength=0.84,
        entry_price=3400.0, stop_price=3230.0, position_pct=0.20,
        sent_at=datetime.now(timezone.utc),
    )
    session.add(log); session.flush()
    so = SignalOutcome(signal_id=log.id, asset="ETH", entry_price=3400.0, outcome="open")
    session.add(so); session.commit()
    assert so.id is not None
    assert so.signal_id == log.id
```

- [ ] **Step 2: Run tests — verify FAIL**

```
docker compose run --rm -v ~/argus/tests:/app/tests -e PYTHONPATH=/app app pytest tests/test_signals.py -k "signal_log or signal_outcome" -v
```

Expected: `ImportError` — `SignalLog` not in models yet.

- [ ] **Step 3: Add models to argus/models.py**

Append at the end of `argus/models.py`:

```python
class SignalLog(Base):
    __tablename__ = "signal_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tier: Mapped[str] = mapped_column(String)           # "whale" | "confluence"
    asset: Mapped[str] = mapped_column(String)
    direction: Mapped[str] = mapped_column(String)      # "bull" | "bear"
    source_ids: Mapped[str] = mapped_column(String)     # JSON list of ints
    signal_strength: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    stop_price: Mapped[float] = mapped_column(Float)
    position_pct: Mapped[float] = mapped_column(Float)
    sent_at: Mapped[datetime] = mapped_column(TZDateTime())


class SignalOutcome(Base):
    __tablename__ = "signal_outcomes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signal_log.id"))
    asset: Mapped[str] = mapped_column(String)
    entry_price: Mapped[float] = mapped_column(Float)
    price_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_7d: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_favorable_excursion: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_adverse_excursion: Mapped[float | None] = mapped_column(Float, nullable=True)
    hit_stop: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)  # open|win|loss|stopped
    evaluated_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
```

- [ ] **Step 4: Run tests — verify PASS**

```
docker compose run --rm -v ~/argus/tests:/app/tests -e PYTHONPATH=/app app pytest tests/test_signals.py -k "signal_log or signal_outcome" -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add argus/models.py tests/test_signals.py
git commit -m "feat(signals): SignalLog + SignalOutcome models"
```

---

## Task 3: Core scoring functions in signals.py

**Files:**
- Create: `argus/signals.py`
- Test: `tests/test_signals.py`

Czyste funkcje — nie wymagają DB.

- [ ] **Step 1: Write failing tests**

```python
from argus.signals import (
    passes_gate, effective_score, combined_strength,
    vol_tier, compute_sizing,
)

def test_passes_gate_true():
    assert passes_gate(0.65, 6) is True

def test_passes_gate_false_low_score():
    assert passes_gate(0.55, 10) is False

def test_passes_gate_false_low_n():
    assert passes_gate(0.70, 4) is False

def test_effective_score_full_confidence():
    # n=30 → mnożnik 1.0
    assert effective_score(0.75, 30) == 0.75

def test_effective_score_partial():
    # n=15 → mnożnik 0.5
    assert abs(effective_score(0.80, 15) - 0.40) < 1e-9

def test_effective_score_low_n():
    # n=5 → mnożnik 5/30 ≈ 0.167
    assert abs(effective_score(0.75, 5) - 0.125) < 1e-6

def test_combined_strength_two_equal():
    # 1 - (1-0.6)*(1-0.6) = 1 - 0.16 = 0.84
    assert abs(combined_strength([0.6, 0.6]) - 0.84) < 1e-9

def test_combined_strength_single():
    assert combined_strength([0.7]) == 0.7

def test_combined_strength_empty():
    assert combined_strength([]) == 0.0

def test_vol_tier_large_cap():
    assert vol_tier("BTC") == "large"
    assert vol_tier("ETH") == "large"

def test_vol_tier_default_mid():
    assert vol_tier("SOL") == "mid"
    assert vol_tier("XOMA") == "mid"

def test_compute_sizing_crypto_large():
    # strength 0.60 → risk 1%, stop 5% → position 20%
    s = compute_sizing(0.60, "BTC", "crypto")
    assert s["risk_pct"] == 0.01
    assert s["stop_pct"] == 0.05
    assert abs(s["position_pct"] - 0.20) < 1e-9
    assert s["vol_tier"] == "large"

def test_compute_sizing_stock_cap():
    # mid cap stock: risk 1%, stop 4% → 25% but capped at 15%
    s = compute_sizing(0.60, "LCID", "stock")
    assert s["position_pct"] == 0.15

def test_compute_sizing_risk_tiers():
    assert compute_sizing(0.60, "BTC", "crypto")["risk_pct"] == 0.01
    assert compute_sizing(0.76, "BTC", "crypto")["risk_pct"] == 0.02
    assert compute_sizing(0.91, "BTC", "crypto")["risk_pct"] == 0.03
```

- [ ] **Step 2: Run tests — verify FAIL**

```
docker compose run --rm -v ~/argus/tests:/app/tests -e PYTHONPATH=/app app pytest tests/test_signals.py -k "gate or effective or combined or vol_tier or compute_sizing" -v
```

Expected: `ImportError` — `argus.signals` doesn't exist.

- [ ] **Step 3: Implement core functions in argus/signals.py**

```python
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
```

- [ ] **Step 4: Run tests — verify PASS**

```
docker compose run --rm -v ~/argus/tests:/app/tests -e PYTHONPATH=/app app pytest tests/test_signals.py -k "gate or effective or combined or vol_tier or compute_sizing" -v
```

Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add argus/signals.py tests/test_signals.py
git commit -m "feat(signals): core scoring functions (passes_gate, effective_score, combined_strength, compute_sizing)"
```

---

## Task 4: check_whale_signals + format_signal_message

**Files:**
- Modify: `argus/signals.py` (append functions)
- Test: `tests/test_signals.py`

- [ ] **Step 1: Write failing tests**

```python
from datetime import datetime, timedelta, timezone
from argus.models import Source, SourceScore, WalletPosition, Asset, SignalLog
from argus.signals import check_whale_signals, format_signal_message, SignalResult

def _make_whale_source(session, handle="hl:abc", score=0.75, n=10):
    src = Source(kind="hyperliquid", handle=handle, display_name=f"HL {handle[-6:]}", active=True)
    session.add(src); session.flush()
    session.add(SourceScore(
        source_id=src.id, horizon="24h", n_claims=n,
        hit_rate=score, avg_return=0.02, decayed_score=score,
        updated_at=datetime.now(timezone.utc),
    ))
    session.commit()
    return src

def _make_position(session, source_id, coin="BTC", side="long", entry_px=67400.0,
                   position_value=100_000.0, opened_minutes_ago=5):
    now = datetime.now(timezone.utc)
    wp = WalletPosition(
        source_id=source_id, coin=coin, side=side, szi=1.0,
        entry_px=entry_px, position_value=position_value,
        opened_ts=now - timedelta(minutes=opened_minutes_ago),
        last_seen_ts=now, open=True,
    )
    session.add(wp); session.commit()
    return wp

def test_whale_signal_generated(session):
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT",
                      scorable=True, active=True))
    session.commit()
    src = _make_whale_source(session, score=0.75, n=10)
    _make_position(session, src.id, coin="BTC", opened_minutes_ago=5)
    results = check_whale_signals(session)
    assert len(results) == 1
    assert results[0].asset == "BTC"
    assert results[0].tier == "whale"
    assert results[0].direction == "bull"

def test_whale_signal_skipped_low_score(session):
    session.add(Asset(symbol="ETH", kind="crypto", binance_symbol="ETHUSDT",
                      scorable=True, active=True))
    session.commit()
    src = _make_whale_source(session, handle="hl:low", score=0.50, n=10)
    _make_position(session, src.id, coin="ETH")
    results = check_whale_signals(session)
    assert results == []

def test_whale_signal_skipped_low_n(session):
    session.add(Asset(symbol="XRP", kind="crypto", binance_symbol="XRPUSDT",
                      scorable=True, active=True))
    session.commit()
    src = _make_whale_source(session, handle="hl:lown", score=0.80, n=3)
    _make_position(session, src.id, coin="XRP")
    results = check_whale_signals(session)
    assert results == []

def test_whale_signal_skipped_old_position(session):
    session.add(Asset(symbol="DOT", kind="crypto", binance_symbol="DOTUSDT",
                      scorable=True, active=True))
    session.commit()
    src = _make_whale_source(session, handle="hl:old", score=0.75, n=10)
    _make_position(session, src.id, coin="DOT", opened_minutes_ago=20)
    results = check_whale_signals(session)
    assert results == []

def test_whale_signal_cooldown(session):
    session.add(Asset(symbol="RUNE", kind="crypto", binance_symbol="RUNEUSDT",
                      scorable=True, active=True))
    session.commit()
    src = _make_whale_source(session, handle="hl:rune", score=0.75, n=10)
    _make_position(session, src.id, coin="RUNE")
    # prior signal in cooldown window
    session.add(SignalLog(
        tier="whale", asset="RUNE", direction="bull", source_ids="[1]",
        signal_strength=0.55, entry_price=1.0, stop_price=0.95,
        position_pct=0.20, sent_at=datetime.now(timezone.utc) - timedelta(hours=1),
    ))
    session.commit()
    results = check_whale_signals(session)
    assert results == []

def test_format_whale_message():
    r = SignalResult(
        tier="whale", asset="BTC", asset_kind="crypto", direction="bull",
        source_ids=[1], source_labels=["HL abc123 · 0.75 · 75%@24h · n=10"],
        signal_strength=0.125, entry_price=67400.0, stop_price=64030.0,
        position_pct=0.20, risk_pct=0.01, stop_pct=0.05,
        vol_tier="large", horizon="24h", window_str=None, whale_notional=100_000.0,
    )
    msg = format_signal_message(r)
    assert "🐋" in msg
    assert "BULLISH BTC/USDT" in msg
    assert "67400" in msg
    assert "64030" in msg
    assert "20%" in msg

def test_format_confluence_message():
    r = SignalResult(
        tier="confluence", asset="ETH", asset_kind="crypto", direction="bear",
        source_ids=[1, 2], source_labels=["src A · 0.61", "src B · 0.63"],
        signal_strength=0.84, entry_price=3400.0, stop_price=3638.0,
        position_pct=0.143, risk_pct=0.01, stop_pct=0.07,
        vol_tier="large", horizon="24h", window_str="1h45m", whale_notional=None,
    )
    msg = format_signal_message(r)
    assert "⚡" in msg
    assert "BEARISH ETH/USDT" in msg
    assert "1h45m" in msg
    assert "strength 0.84" in msg
```

- [ ] **Step 2: Run tests — verify FAIL**

```
docker compose run --rm -v ~/argus/tests:/app/tests -e PYTHONPATH=/app app pytest tests/test_signals.py -k "whale" -v
```

Expected: `ImportError` for `check_whale_signals`.

- [ ] **Step 3: Implement check_whale_signals + format_signal_message in argus/signals.py**

Append to `argus/signals.py`:

```python
def _is_on_cooldown(session, asset: str) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=_COOLDOWN_HOURS)
    return session.scalar(
        select(SignalLog).where(SignalLog.asset == asset, SignalLog.sent_at >= cutoff)
    ) is not None


def _max_n_claims(session, source_id: int) -> int:
    return session.scalar(
        select(func.max(SourceScore.n_claims)).where(SourceScore.source_id == source_id)
    ) or 0


def _get_source_score(session, source_id: int, horizon: str):
    return session.scalar(
        select(SourceScore).where(
            SourceScore.source_id == source_id,
            SourceScore.horizon == horizon,
        )
    )


def _last_price(session, asset: str):
    row = session.scalar(
        select(Price).where(Price.asset == asset).order_by(Price.ts.desc())
    )
    return row.price if row else None


def _save_signal(session, result: "SignalResult") -> SignalLog:
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
        n = _max_n_claims(session, pos.source_id)
        ss = _get_source_score(session, pos.source_id, "24h")
        if ss is None or not passes_gate(ss.decayed_score, n):
            continue
        if _is_on_cooldown(session, pos.coin):
            continue
        eff = effective_score(ss.decayed_score, n)
        sizing = compute_sizing(eff, pos.coin, "crypto")
        direction = "bull" if pos.side == "long" else "bear"
        sp = sizing["stop_pct"]
        stop = pos.entry_px * (1 - sp) if direction == "bull" else pos.entry_px * (1 + sp)
        label = (f"{source.display_name} · {ss.decayed_score:.2f} · "
                 f"{ss.hit_rate:.0%}@24h · n={n}")
        results.append(SignalResult(
            tier="whale",
            asset=pos.coin,
            asset_kind="crypto",
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


def format_signal_message(result: "SignalResult") -> str:
    emoji = "🐋" if result.tier == "whale" else "⚡"
    dir_str = "BULLISH" if result.direction == "bull" else "BEARISH"
    suffix = "USDT" if result.asset_kind == "crypto" else "USD"
    tier_str = ("WHALE SIGNAL" if result.tier == "whale"
                else f"CONFLUENCE · strength {result.signal_strength:.2f}")
    lines = [f"{emoji} {tier_str} · {dir_str} {result.asset}/{suffix}", ""]
    for label in result.source_labels:
        lines.append(f"• {label}")
    if result.tier == "confluence" and result.window_str:
        lines.append(f"Zgodność: {len(result.source_ids)} źródła · okno {result.window_str}")
    if result.whale_notional is not None:
        lines.append(f"Pozycja whale: ${result.whale_notional:,.0f} @ ${result.entry_price:,.2f}")
    lines += [
        "",
        f"Entry teraz: ~${result.entry_price:,.2f}",
        f"Stop-loss: ${result.stop_price:,.2f} (-{result.stop_pct:.0%}, {result.vol_tier} cap)",
        f"Pozycja: {result.position_pct:.0%} portfela (ryzyko {result.risk_pct:.0%})",
        f"Horyzont: {result.horizon}",
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests — verify PASS**

```
docker compose run --rm -v ~/argus/tests:/app/tests -e PYTHONPATH=/app app pytest tests/test_signals.py -k "whale or format" -v
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add argus/signals.py tests/test_signals.py
git commit -m "feat(signals): check_whale_signals + format_signal_message"
```

---

## Task 5: check_confluence_signals

**Files:**
- Modify: `argus/signals.py` (append)
- Test: `tests/test_signals.py`

- [ ] **Step 1: Write failing tests**

```python
from argus.models import Claim, Price
from argus.signals import check_confluence_signals

def _make_rss_source(session, handle, score=0.65, n=8):
    src = Source(kind="rss", handle=handle, display_name=handle, active=True)
    session.add(src); session.flush()
    session.add(SourceScore(
        source_id=src.id, horizon="24h", n_claims=n,
        hit_rate=score, avg_return=0.01, decayed_score=score,
        updated_at=datetime.now(timezone.utc),
    ))
    session.commit()
    return src

def _make_reddit_source(session, handle, score=0.65, n=8):
    src = Source(kind="reddit", handle=handle, display_name=handle, active=True)
    session.add(src); session.flush()
    session.add(SourceScore(
        source_id=src.id, horizon="24h", n_claims=n,
        hit_rate=score, avg_return=0.01, decayed_score=score,
        updated_at=datetime.now(timezone.utc),
    ))
    session.commit()
    return src

def _make_claim(session, source_id, asset, direction="bull", minutes_ago=30):
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    c = Claim(
        source_id=source_id, asset=asset, direction=direction,
        confidence=0.7, method="rule", entry_price=100.0, entry_ts=ts, status="open",
    )
    session.add(c); session.commit()
    return c

def _make_price(session, asset, price):
    session.add(Price(asset=asset, ts=datetime.now(timezone.utc), price=price))
    session.commit()

def test_confluence_signal_generated(session):
    session.add(Asset(symbol="SOL", kind="crypto", binance_symbol="SOLUSDT",
                      scorable=True, active=True))
    session.commit()
    rss_src = _make_rss_source(session, "rss:theblock", score=0.65, n=8)
    red_src = _make_reddit_source(session, "reddit:ssb", score=0.65, n=8)
    _make_claim(session, rss_src.id, "SOL", "bull")
    _make_claim(session, red_src.id, "SOL", "bull")
    _make_price(session, "SOL", 150.0)
    results = check_confluence_signals(session)
    assert len(results) == 1
    assert results[0].asset == "SOL"
    assert results[0].tier == "confluence"

def test_confluence_skipped_same_kind(session):
    session.add(Asset(symbol="ONDO", kind="crypto", binance_symbol="ONDOUSDT",
                      scorable=True, active=True))
    session.commit()
    r1 = _make_reddit_source(session, "reddit:a", score=0.65, n=8)
    r2 = _make_reddit_source(session, "reddit:b", score=0.65, n=8)
    _make_claim(session, r1.id, "ONDO", "bull")
    _make_claim(session, r2.id, "ONDO", "bull")
    _make_price(session, "ONDO", 1.0)
    results = check_confluence_signals(session)
    assert results == []

def test_confluence_skipped_low_strength(session):
    session.add(Asset(symbol="HBAR", kind="crypto", binance_symbol="HBARUSDT",
                      scorable=True, active=True))
    session.commit()
    # n=5 → effective = 0.60 * (5/30) = 0.10; combined(0.10, 0.10) = 0.19 < 0.80
    r = _make_rss_source(session, "rss:x", score=0.60, n=5)
    rd = _make_reddit_source(session, "reddit:x", score=0.60, n=5)
    _make_claim(session, r.id, "HBAR", "bull")
    _make_claim(session, rd.id, "HBAR", "bull")
    _make_price(session, "HBAR", 0.10)
    results = check_confluence_signals(session)
    assert results == []

def test_confluence_top3_limit(session):
    for sym, bs in [("BTC", "BTCUSDT"), ("ETH", "ETHUSDT"), ("XRP", "XRPUSDT"), ("DOT", "DOTUSDT")]:
        session.add(Asset(symbol=sym, kind="crypto", binance_symbol=bs,
                          scorable=True, active=True))
        _make_price(session, sym, 100.0)
    session.commit()
    for i, sym in enumerate(["BTC", "ETH", "XRP", "DOT"]):
        r = _make_rss_source(session, f"rss:{sym}", score=0.80, n=30)
        rd = _make_reddit_source(session, f"red:{sym}", score=0.80, n=30)
        _make_claim(session, r.id, sym, "bull")
        _make_claim(session, rd.id, sym, "bull")
    results = check_confluence_signals(session)
    assert len(results) <= 3
```

- [ ] **Step 2: Run tests — verify FAIL**

```
docker compose run --rm -v ~/argus/tests:/app/tests -e PYTHONPATH=/app app pytest tests/test_signals.py -k "confluence" -v
```

Expected: `ImportError` for `check_confluence_signals`.

- [ ] **Step 3: Implement check_confluence_signals in argus/signals.py**

Append to `argus/signals.py`:

```python
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
        if ss is None or not passes_gate(ss.decayed_score, n):
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
        eff_scores = [effective_score(e[2].decayed_score, e[3]) for e in entries]
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
```

- [ ] **Step 4: Run tests — verify PASS**

```
docker compose run --rm -v ~/argus/tests:/app/tests -e PYTHONPATH=/app app pytest tests/test_signals.py -k "confluence" -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add argus/signals.py tests/test_signals.py
git commit -m "feat(signals): check_confluence_signals"
```

---

## Task 6: evaluate_signal_outcomes + send_signals helpers

**Files:**
- Modify: `argus/signals.py` (append)
- Test: `tests/test_signals.py`

- [ ] **Step 1: Write failing tests**

```python
from argus.signals import evaluate_signal_outcomes, send_signals

def _make_signal_log(session, asset="BTC", direction="bull",
                     entry=67400.0, stop=64030.0, hours_ago=25):
    log = SignalLog(
        tier="whale", asset=asset, direction=direction,
        source_ids="[1]", signal_strength=0.55,
        entry_price=entry, stop_price=stop, position_pct=0.20,
        sent_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
    )
    session.add(log); session.flush()
    so = SignalOutcome(signal_id=log.id, asset=asset, entry_price=entry, outcome="open")
    session.add(so); session.commit()
    return log, so

def test_evaluate_sets_price_24h(session):
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT",
                      scorable=True, active=True))
    session.commit()
    log, so = _make_signal_log(session, hours_ago=25)
    _make_price(session, "BTC", 68000.0)
    n = evaluate_signal_outcomes(session)
    assert n == 1
    session.refresh(so)
    assert so.price_24h == 68000.0
    assert so.outcome in ("win", "loss", "open")

def test_evaluate_marks_stopped(session):
    session.add(Asset(symbol="ETH", kind="crypto", binance_symbol="ETHUSDT",
                      scorable=True, active=True))
    session.commit()
    # bull signal, stop=3230, current price below stop
    log, so = _make_signal_log(session, asset="ETH", direction="bull",
                               entry=3400.0, stop=3230.0, hours_ago=25)
    _make_price(session, "ETH", 3000.0)  # below stop
    evaluate_signal_outcomes(session)
    session.refresh(so)
    assert so.hit_stop is True
    assert so.outcome == "stopped"

def test_evaluate_skips_recent_signals(session):
    session.add(Asset(symbol="XRP", kind="crypto", binance_symbol="XRPUSDT",
                      scorable=True, active=True))
    session.commit()
    log, so = _make_signal_log(session, asset="XRP", hours_ago=5)  # only 5h old
    _make_price(session, "XRP", 1.0)
    n = evaluate_signal_outcomes(session)
    assert n == 0

def test_send_signals_calls_telegram(session):
    from unittest.mock import patch
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT",
                      scorable=True, active=True))
    session.commit()
    src = _make_whale_source(session, handle="hl:send", score=0.75, n=10)
    _make_position(session, src.id, coin="BTC", opened_minutes_ago=5)
    with patch("argus.signals.send_message") as mock_send:
        send_signals(session)
    mock_send.assert_called_once()
    assert "BTC" in mock_send.call_args.args[0]
```

- [ ] **Step 2: Run tests — verify FAIL**

```
docker compose run --rm -v ~/argus/tests:/app/tests -e PYTHONPATH=/app app pytest tests/test_signals.py -k "evaluate or send_signals" -v
```

- [ ] **Step 3: Implement evaluate_signal_outcomes + send_signals in argus/signals.py**

Append to `argus/signals.py`:

```python
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
        asset_row = session.scalar(select(Asset).where(Asset.symbol == so.asset))
        if asset_row is None:
            continue
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
    from argus.telegram import send_message
    whale = check_whale_signals(session)
    confluence = check_confluence_signals(session)
    for result in whale + confluence:
        msg = format_signal_message(result)
        send_message(msg)
        _save_signal(session, result)
        logger.info("signal sent: %s %s %s strength=%.2f",
                    result.tier, result.direction, result.asset, result.signal_strength)
```

- [ ] **Step 4: Run tests — verify PASS**

```
docker compose run --rm -v ~/argus/tests:/app/tests -e PYTHONPATH=/app app pytest tests/test_signals.py -k "evaluate or send_signals" -v
```

Expected: 4 passed.

- [ ] **Step 5: Run all signal tests**

```
docker compose run --rm -v ~/argus/tests:/app/tests -e PYTHONPATH=/app app pytest tests/test_signals.py -v
```

Expected: wszystkie passed (≥ 23 testów).

- [ ] **Step 6: Commit**

```bash
git add argus/signals.py tests/test_signals.py
git commit -m "feat(signals): evaluate_signal_outcomes + send_signals"
```

---

## Task 7: Jobs w main.py

**Files:**
- Modify: `argus/main.py`

Nie wymagają osobnych testów — logika jest w signals.py (przetestowana). Tylko podpięcie do schedulera.

- [ ] **Step 1: Dodaj trzy funkcje job i zarejestruj w schedulerze**

W `argus/main.py` dodaj po `_heartbeat_job`:

```python
def _whale_signal_job():
    from argus.signals import send_signals
    with SessionLocal() as s:
        send_signals(s)


def _signal_outcomes_job():
    from argus.signals import evaluate_signal_outcomes
    import logging
    with SessionLocal() as s:
        n = evaluate_signal_outcomes(s)
    logging.getLogger(__name__).info("signal_outcomes: evaluated %d", n)
```

W funkcji `bootstrap()`, po linii `sched.add_interval("heartbeat", _heartbeat_job, minutes=5)` dodaj:

```python
    sched.add_interval("whale_signal", _whale_signal_job, minutes=10)
    sched.add_interval("signal_outcomes", _signal_outcomes_job, minutes=360)
```

Uwaga: `check_confluence_signals` jest wywoływany przez `send_signals` (który jest w `_whale_signal_job`). Nie potrzeba osobnego jobu dla confluence — `send_signals` sprawdza oba tiery w jednym wywołaniu.

- [ ] **Step 2: Uruchom istniejące testy żeby sprawdzić brak regresji**

```
docker compose run --rm -v ~/argus/tests:/app/tests -e PYTHONPATH=/app app pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: wszystkie testy pass (≥ dotychczasowe + nowe).

- [ ] **Step 3: Commit**

```bash
git add argus/main.py
git commit -m "feat(signals): whale_signal + signal_outcomes jobs in scheduler"
```

---

## Task 8: Deploy na VPS

- [ ] **Step 1: Skopiuj pliki na VPS**

```bash
scp -i "C:/ai/ssh-key-2026-05-19.key" \
  argus/argus/telegram.py \
  argus/argus/signals.py \
  argus/argus/models.py \
  argus/argus/main.py \
  ubuntu@84.235.174.129:/home/ubuntu/argus/argus/
scp -i "C:/ai/ssh-key-2026-05-19.key" \
  argus/tests/test_signals.py \
  ubuntu@84.235.174.129:/home/ubuntu/argus/tests/
```

- [ ] **Step 2: Uruchom testy na VPS**

```bash
ssh -i "C:/ai/ssh-key-2026-05-19.key" ubuntu@84.235.174.129 \
  "cd /home/ubuntu/argus && docker compose run --rm -v ~/argus/tests:/app/tests -e PYTHONPATH=/app app pytest tests/test_signals.py -v 2>&1 | tail -30"
```

Expected: wszystkie test_signals.py pass.

- [ ] **Step 3: Rebuild i restart app**

```bash
ssh -i "C:/ai/ssh-key-2026-05-19.key" ubuntu@84.235.174.129 \
  "cd /home/ubuntu/argus && docker compose build app && docker compose up -d app"
```

- [ ] **Step 4: Sprawdź logi po 15s**

```bash
ssh -i "C:/ai/ssh-key-2026-05-19.key" ubuntu@84.235.174.129 \
  "sleep 15 && docker compose -f /home/ubuntu/argus/docker-compose.yml logs app --tail=20"
```

Expected: `Application startup complete`, brak błędów importu, `whale_signal` i `signal_outcomes` jopy widoczne w logach APScheduler.

- [ ] **Step 5: Sprawdź czy tabele utworzone**

```bash
ssh -i "C:/ai/ssh-key-2026-05-19.key" ubuntu@84.235.174.129 \
  "docker compose -f /home/ubuntu/argus/docker-compose.yml exec -T db psql -U argus -d argus -c '\dt signal*'"
```

Expected: `signal_log` i `signal_outcomes` w liście tabel.

- [ ] **Step 6: Commit końcowy**

```bash
git add -A
git commit -m "feat: Argus Signal Notifier — whale + confluence alerts z Telegram i signal_outcomes tracking"
```
