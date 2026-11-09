# Argus — Faza 0 + Faza 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zbudować pełny mierzalny cykl `claim → outcome → source score → ranking` dla agenta Argus, działający na watchliście krypto+akcje, z minimalnym dashboardem — bez LLM.

**Architecture:** Niezależny stack Python (FastAPI + APScheduler + SQLAlchemy/Postgres) w Dockerze na Oracle Ampere A1. Collectory zapisują `items`, inline-regex ekstrahuje `claims` (z `claim_audit`), evaluator po horyzontach 1h/24h/7d liczy `outcomes` względem ceny (CoinGecko/Binance dla krypto, yfinance dla akcji), scorer agreguje wiarygodność per (źródło, aktywo). API+statyczny dashboard pokazują trend-lean i ranking źródeł.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, APScheduler, httpx, feedparser, yfinance, pytest. DB: Postgres (prod) / SQLite in-memory (testy — abstrakcja SQLAlchemy).

**Spec:** `docs/superpowers/specs/2026-06-02-argus-trend-credibility-agent-design.md`

---

## Konwencje współdzielone (sygnatury — używane spójnie w zadaniach)

- Kierunki: `"bull" | "bear" | "neutral"`.
- Metody ekstrakcji: `"position" | "rule" | "llm"`.
- Horyzonty: `HORIZONS = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7)}`.
- Progi hit: `THRESHOLDS = {"1h": 0.005, "24h": 0.015, "7d": 0.04}` (frakcje, nie %).
- `PARSER_VERSION = "rule-v1"`.
- Price API: `get_spot_price(asset: Asset) -> float`, `get_historical_price(asset: Asset, when: datetime) -> float`.
- Extractor: `extract_claims(text: str, assets: list[Asset]) -> list[ParsedClaim]`; `ParsedClaim(asset_symbol, direction, confidence, target_price)`.
- Scorer: `recompute_scores(session, *, tau_days=14, alpha=2, beta=2, k_min=5) -> None`.
- Analytics: `trend_lean(session, horizon: str) -> list[dict]`.
- Wszystkie czasy = timezone-aware UTC (`datetime.now(timezone.utc)`).

## Struktura plików

```
argus/
  docker-compose.yml          # Task 13
  Dockerfile                  # Task 13
  requirements.txt            # Task 1
  .env.example                # Task 1
  config/
    watchlist.yaml            # Task 0/3 — seed assets
    sources.yaml              # Task 0/3 — seed RSS sources
  argus/
    __init__.py
    config.py                 # Task 1 — Settings (env)
    db.py                     # Task 1 — engine/session/Base
    models.py                 # Task 2 — wszystkie tabele ORM
    seed.py                   # Task 3 — upsert assets+sources z YAML
    prices.py                 # Task 4 — provider crypto + stock
    extract.py                # Task 5 — inline regex claim extractor
    collectors/__init__.py
    collectors/rss.py         # Task 6 — RSS collector
    evaluator.py              # Task 7 — outcome evaluator
    scorer.py                 # Task 8 — source scorer
    analytics.py              # Task 9 — trend-lean
    api.py                    # Task 10 — FastAPI JSON + static
    scheduler/__init__.py
    scheduler/base.py         # Task 11 — interfejs
    scheduler/apscheduler_impl.py  # Task 11
    web/index.html            # Task 12 — dashboard
    web/app.js                # Task 12
  tests/
    conftest.py               # Task 1 — fixtures (in-memory session)
    test_models.py            # Task 2
    test_seed.py              # Task 3
    test_prices.py            # Task 4
    test_extract.py           # Task 5
    test_rss.py               # Task 6
    test_evaluator.py         # Task 7
    test_scorer.py            # Task 8
    test_analytics.py         # Task 9
    test_api.py               # Task 10
    test_scheduler.py         # Task 11
```

---

### Task 0: Faza 0 — spike dostępu do danych + finalizacja seedu

**Files:**
- Create: `argus/docs/phase0-findings.md`
- Create: `argus/config/watchlist.yaml`
- Create: `argus/config/sources.yaml`

Investigation task (bez TDD — produkuje wiedzę + pliki seed).

- [ ] **Step 1: Sprawdź dostęp Hyperdash i Coinglass**

Wykonaj i zapisz wynik (status, czy jest JSON API, czy wymaga klucza/scrapingu):

```bash
curl -sS -o /dev/null -w "hyperdash root: %{http_code}\n" https://hyperdash.info/
curl -sS "https://hyperdash.info/api/..." -w "\n%{http_code}\n" | head -c 500   # poszukaj realnego endpointu w devtools/network
curl -sS "https://open-api.coinglass.com/public/v2/liquidation_map?symbol=BTC" -w "\n%{http_code}\n" | head -c 500
```

Kryterium decyzji: jeśli Hyperdash NIE ma publicznego JSON API → zostaje w backlogu Fazy 1.5 (nie blokuje Fazy 1, cykl działa na RSS). Coinglass i tak tylko market-context (Faza 3). Zapisz wnioski do `argus/docs/phase0-findings.md`.

- [ ] **Step 2: Zweryfikuj CoinGecko id + Binance symbol dla 14 krypto**

Dla każdego tickera potwierdź `coingecko_id` (uwaga: XAI, GROK, ALU mają duplikaty — wybierz właściwy po market cap / kontrakcie):

```bash
curl -sS "https://api.coingecko.com/api/v3/search?query=ondo" | python -m json.tool | head -40
curl -sS "https://api.binance.com/api/v3/ticker/price?symbol=ONDOUSDT" -w "\n%{http_code}\n"
```

- [ ] **Step 3: Zweryfikuj yfinance dla 7 akcji**

```bash
python -c "import yfinance as yf; print({t: yf.Ticker(t).fast_info.get('lastPrice') for t in ['XOMA','BYND','DLNG','LCID','NFE','NTR','PLG']})"
```

- [ ] **Step 4: Zapisz `config/watchlist.yaml`**

```yaml
# scorable=true → oceniane w Fazie 1 (ma źródło ceny)
assets:
  # --- krypto (CoinGecko/Binance) ---
  - {symbol: BTC,    kind: crypto, coingecko_id: bitcoin,                  binance_symbol: BTCUSDT,    scorable: true}
  - {symbol: ETH,    kind: crypto, coingecko_id: ethereum,                 binance_symbol: ETHUSDT,    scorable: true}
  - {symbol: XRP,    kind: crypto, coingecko_id: ripple,                   binance_symbol: XRPUSDT,    scorable: true}
  - {symbol: DOT,    kind: crypto, coingecko_id: polkadot,                 binance_symbol: DOTUSDT,    scorable: true}
  - {symbol: JUP,    kind: crypto, coingecko_id: jupiter-exchange-solana,  binance_symbol: JUPUSDT,    scorable: true}
  - {symbol: HBAR,   kind: crypto, coingecko_id: hedera-hashgraph,         binance_symbol: HBARUSDT,   scorable: true}
  - {symbol: RENDER, kind: crypto, coingecko_id: render-token,             binance_symbol: RENDERUSDT, scorable: true}
  - {symbol: AERO,   kind: crypto, coingecko_id: aerodrome-finance,        binance_symbol: AEROUSDT,   scorable: true}
  - {symbol: XAI,    kind: crypto, coingecko_id: VERIFY_IN_STEP_2,         binance_symbol: XAIUSDT,    scorable: true}
  - {symbol: ONDO,   kind: crypto, coingecko_id: ondo-finance,             binance_symbol: ONDOUSDT,   scorable: true}
  - {symbol: AEVO,   kind: crypto, coingecko_id: aevo-exchange,            binance_symbol: AEVOUSDT,   scorable: true}
  - {symbol: GROK,   kind: crypto, coingecko_id: VERIFY_IN_STEP_2,         binance_symbol: GROKUSDT,   scorable: true}
  - {symbol: ALU,    kind: crypto, coingecko_id: VERIFY_IN_STEP_2,         binance_symbol: ALUUSDT,    scorable: true}
  - {symbol: RUNE,   kind: crypto, coingecko_id: thorchain,                binance_symbol: RUNEUSDT,   scorable: true}
  # --- akcje (yfinance, symbol = ticker) ---
  - {symbol: XOMA, kind: stock, yf_symbol: XOMA, scorable: true}
  - {symbol: BYND, kind: stock, yf_symbol: BYND, scorable: true}
  - {symbol: DLNG, kind: stock, yf_symbol: DLNG, scorable: true}
  - {symbol: LCID, kind: stock, yf_symbol: LCID, scorable: true}
  - {symbol: NFE,  kind: stock, yf_symbol: NFE,  scorable: true}
  - {symbol: NTR,  kind: stock, yf_symbol: NTR,  scorable: true}
  - {symbol: PLG,  kind: stock, yf_symbol: PLG,  scorable: true}
  # --- indeksy/makro (seed, ale NIE oceniane w Fazie 1) ---
  - {symbol: TOTAL,  kind: index, scorable: false}
  - {symbol: BTC.D,  kind: index, scorable: false}
  - {symbol: ETHBTC, kind: index, scorable: false}
  - {symbol: USDT,   kind: macro, scorable: false}
  - {symbol: SILVER, kind: macro, scorable: false}
  - {symbol: CNY,    kind: macro, scorable: false}
```

- [ ] **Step 5: Zapisz `config/sources.yaml`** (start: solidne RSS krypto)

```yaml
sources:
  - {kind: rss, handle: "https://www.coindesk.com/arc/outboundfeeds/rss/", display_name: CoinDesk}
  - {kind: rss, handle: "https://cointelegraph.com/rss",                   display_name: CoinTelegraph}
  - {kind: rss, handle: "https://decrypt.co/feed",                         display_name: Decrypt}
  - {kind: rss, handle: "https://www.theblock.co/rss.xml",                 display_name: TheBlock}
```

- [ ] **Step 6: Commit**

```bash
git add argus/docs/phase0-findings.md argus/config/watchlist.yaml argus/config/sources.yaml
git commit -m "chore(argus): phase-0 spike findings + watchlist/sources seed"
```

---

### Task 1: Scaffold projektu + konfiguracja

**Files:**
- Create: `argus/requirements.txt`, `argus/.env.example`
- Create: `argus/argus/__init__.py`, `argus/argus/config.py`, `argus/argus/db.py`
- Create: `argus/tests/conftest.py`

- [ ] **Step 1: `requirements.txt`**

```
fastapi==0.115.*
uvicorn[standard]==0.32.*
sqlalchemy==2.0.*
psycopg2-binary==2.9.*
apscheduler==3.10.*
httpx==0.27.*
feedparser==6.0.*
yfinance==0.2.*
pyyaml==6.0.*
pytest==8.3.*
```

- [ ] **Step 2: `.env.example`**

```
ARGUS_DB_URL=postgresql+psycopg2://argus:argus@db:5432/argus
ARGUS_WATCHLIST=config/watchlist.yaml
ARGUS_SOURCES=config/sources.yaml
```

- [ ] **Step 3: `argus/config.py`**

```python
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    db_url: str = os.getenv("ARGUS_DB_URL", "sqlite:///argus.db")
    watchlist_path: str = os.getenv("ARGUS_WATCHLIST", "config/watchlist.yaml")
    sources_path: str = os.getenv("ARGUS_SOURCES", "config/sources.yaml")

settings = Settings()
```

- [ ] **Step 4: `argus/db.py`**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from argus.config import settings

class Base(DeclarativeBase):
    pass

engine = create_engine(settings.db_url, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
```

- [ ] **Step 5: `tests/conftest.py`** (in-memory SQLite session)

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from argus.db import Base
import argus.models  # noqa: F401  (rejestruje tabele)

@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    s = Sess()
    yield s
    s.close()
```

- [ ] **Step 6: Commit**

```bash
git add argus/requirements.txt argus/.env.example argus/argus/ argus/tests/conftest.py
git commit -m "chore(argus): scaffold + config + db base"
```

---

### Task 2: Modele ORM

**Files:**
- Create: `argus/argus/models.py`
- Test: `argus/tests/test_models.py`

- [ ] **Step 1: Test (roundtrip każdej tabeli)**

```python
from datetime import datetime, timezone
from argus.models import (Asset, Source, Item, Claim, ClaimAudit,
                          Price, Outcome, SourceAssetScore, SourceScore)

def test_full_chain_roundtrip(session):
    a = Asset(symbol="BTC", kind="crypto", coingecko_id="bitcoin",
              binance_symbol="BTCUSDT", scorable=True)
    s = Source(kind="rss", handle="http://x", display_name="X")
    session.add_all([a, s]); session.flush()
    it = Item(source_id=s.id, external_id="e1", title="t", text="long btc",
              url="u", published_at=datetime.now(timezone.utc))
    session.add(it); session.flush()
    c = Claim(source_id=s.id, item_id=it.id, asset="BTC", direction="bull",
              confidence=0.8, method="rule", entry_price=100.0,
              entry_ts=datetime.now(timezone.utc), status="open")
    session.add(c); session.flush()
    session.add(ClaimAudit(claim_id=c.id, raw_text="long btc",
                           parsed_claim={"direction": "bull"}, parser_version="rule-v1"))
    session.add(Outcome(claim_id=c.id, horizon="24h",
                        eval_ts=datetime.now(timezone.utc), price_at_horizon=102.0,
                        return_pct=0.02, hit=True))
    session.commit()
    assert session.query(Claim).one().direction == "bull"
    assert session.query(Outcome).one().hit is True
```

- [ ] **Step 2: Run → FAIL** — `Run: cd argus && pytest tests/test_models.py -v` → ImportError (models nie istnieją).

- [ ] **Step 3: `argus/models.py`**

```python
from datetime import datetime
from sqlalchemy import (String, Float, Boolean, Integer, DateTime, ForeignKey, JSON, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column
from argus.db import Base

class Asset(Base):
    __tablename__ = "assets"
    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String)                 # crypto|stock|index|macro
    coingecko_id: Mapped[str | None] = mapped_column(String, nullable=True)
    binance_symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    yf_symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    scorable: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Source(Base):
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String)                 # rss|hyperdash|reddit|onchain
    handle: Mapped[str] = mapped_column(String, unique=True)
    display_name: Mapped[str] = mapped_column(String)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Item(Base):
    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    external_id: Mapped[str] = mapped_column(String)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    text: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class Claim(Base):
    __tablename__ = "claims"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"), nullable=True)
    asset: Mapped[str] = mapped_column(ForeignKey("assets.symbol"))
    direction: Mapped[str] = mapped_column(String)            # bull|bear|neutral
    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String)               # position|rule|llm
    entry_price: Mapped[float] = mapped_column(Float)
    entry_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String, default="open")

class ClaimAudit(Base):
    __tablename__ = "claim_audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"))
    raw_text: Mapped[str] = mapped_column(String)
    parsed_claim: Mapped[dict] = mapped_column(JSON)
    parser_version: Mapped[str] = mapped_column(String)

class Price(Base):
    __tablename__ = "prices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset: Mapped[str] = mapped_column(ForeignKey("assets.symbol"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    price: Mapped[float] = mapped_column(Float)

class Outcome(Base):
    __tablename__ = "outcomes"
    __table_args__ = (UniqueConstraint("claim_id", "horizon"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"))
    horizon: Mapped[str] = mapped_column(String)              # 1h|24h|7d
    eval_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    price_at_horizon: Mapped[float] = mapped_column(Float)
    return_pct: Mapped[float] = mapped_column(Float)
    hit: Mapped[bool] = mapped_column(Boolean)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class SourceAssetScore(Base):
    __tablename__ = "source_asset_scores"
    __table_args__ = (UniqueConstraint("source_id", "asset", "horizon"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    asset: Mapped[str] = mapped_column(String)
    horizon: Mapped[str] = mapped_column(String)
    n_claims: Mapped[int] = mapped_column(Integer)
    n_hits: Mapped[int] = mapped_column(Integer)
    hit_rate: Mapped[float] = mapped_column(Float)
    avg_return: Mapped[float] = mapped_column(Float)
    decayed_score: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class SourceScore(Base):
    __tablename__ = "source_scores"
    __table_args__ = (UniqueConstraint("source_id", "horizon"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    horizon: Mapped[str] = mapped_column(String)
    n_claims: Mapped[int] = mapped_column(Integer)
    hit_rate: Mapped[float] = mapped_column(Float)
    avg_return: Mapped[float] = mapped_column(Float)
    decayed_score: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 4: Run → PASS** — `cd argus && pytest tests/test_models.py -v`

- [ ] **Step 5: Commit** — `git add argus/argus/models.py argus/tests/test_models.py && git commit -m "feat(argus): ORM models for full claim->score chain"`

---

### Task 3: Seed assets + sources z YAML

**Files:**
- Create: `argus/argus/seed.py`
- Test: `argus/tests/test_seed.py`

- [ ] **Step 1: Test (idempotentny upsert)**

```python
import yaml
from argus.seed import seed_assets, seed_sources
from argus.models import Asset, Source

def test_seed_idempotent(session, tmp_path):
    wl = tmp_path / "wl.yaml"
    wl.write_text(yaml.safe_dump({"assets": [
        {"symbol": "BTC", "kind": "crypto", "coingecko_id": "bitcoin",
         "binance_symbol": "BTCUSDT", "scorable": True}]}))
    sr = tmp_path / "sr.yaml"
    sr.write_text(yaml.safe_dump({"sources": [
        {"kind": "rss", "handle": "http://x", "display_name": "X"}]}))
    seed_assets(session, str(wl)); seed_sources(session, str(sr))
    seed_assets(session, str(wl)); seed_sources(session, str(sr))  # 2x
    assert session.query(Asset).count() == 1
    assert session.query(Source).count() == 1
    assert session.query(Asset).one().scorable is True
```

- [ ] **Step 2: Run → FAIL** (ImportError).

- [ ] **Step 3: `argus/seed.py`**

```python
import yaml
from sqlalchemy import select
from argus.models import Asset, Source

def seed_assets(session, path: str) -> None:
    data = yaml.safe_load(open(path, encoding="utf-8"))
    for a in data["assets"]:
        existing = session.get(Asset, a["symbol"])
        if existing is None:
            session.add(Asset(**a))
        else:
            for k, v in a.items():
                setattr(existing, k, v)
    session.commit()

def seed_sources(session, path: str) -> None:
    data = yaml.safe_load(open(path, encoding="utf-8"))
    for s in data["sources"]:
        existing = session.scalar(select(Source).where(Source.handle == s["handle"]))
        if existing is None:
            session.add(Source(**s))
        else:
            existing.display_name = s["display_name"]
    session.commit()
```

- [ ] **Step 4: Run → PASS** — `cd argus && pytest tests/test_seed.py -v`

- [ ] **Step 5: Commit** — `git add argus/argus/seed.py argus/tests/test_seed.py && git commit -m "feat(argus): idempotent YAML seeding for assets+sources"`

---

### Task 4: Moduł cen (crypto + stock provider)

**Files:**
- Create: `argus/argus/prices.py`
- Test: `argus/tests/test_prices.py`

- [ ] **Step 1: Test (dispatch + mock)**

```python
from datetime import datetime, timezone
from unittest.mock import patch
from argus.models import Asset
from argus.prices import get_spot_price, get_historical_price

def test_crypto_spot_uses_binance():
    a = Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT")
    with patch("argus.prices._binance_spot", return_value=67000.0) as m:
        assert get_spot_price(a) == 67000.0
        m.assert_called_once_with("BTCUSDT")

def test_stock_spot_uses_yf():
    a = Asset(symbol="LCID", kind="stock", yf_symbol="LCID")
    with patch("argus.prices._yf_spot", return_value=6.28) as m:
        assert get_spot_price(a) == 6.28
        m.assert_called_once_with("LCID")

def test_historical_crypto():
    a = Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT")
    when = datetime(2026, 6, 1, tzinfo=timezone.utc)
    with patch("argus.prices._binance_historical", return_value=66000.0):
        assert get_historical_price(a, when) == 66000.0

def test_unsupported_kind_raises():
    a = Asset(symbol="TOTAL", kind="index")
    try:
        get_spot_price(a); assert False
    except ValueError:
        pass
```

- [ ] **Step 2: Run → FAIL** (ImportError).

- [ ] **Step 3: `argus/prices.py`**

```python
from datetime import datetime, timezone
import httpx
import yfinance as yf

_BINANCE = "https://api.binance.com"

def _binance_spot(symbol: str) -> float:
    r = httpx.get(f"{_BINANCE}/api/v3/ticker/price", params={"symbol": symbol}, timeout=15)
    r.raise_for_status()
    return float(r.json()["price"])

def _binance_historical(symbol: str, when: datetime) -> float:
    start_ms = int(when.timestamp() * 1000)
    r = httpx.get(f"{_BINANCE}/api/v3/klines",
                  params={"symbol": symbol, "interval": "1m", "startTime": start_ms, "limit": 1},
                  timeout=15)
    r.raise_for_status()
    klines = r.json()
    if not klines:
        raise ValueError(f"no kline for {symbol} at {when}")
    return float(klines[0][4])  # close

def _yf_spot(symbol: str) -> float:
    return float(yf.Ticker(symbol).fast_info["lastPrice"])

def _yf_historical(symbol: str, when: datetime) -> float:
    hist = yf.Ticker(symbol).history(start=when.date(), period="5d")
    if hist.empty:
        raise ValueError(f"no yf history for {symbol} at {when}")
    return float(hist["Close"].iloc[0])  # najbliższy dostępny close >= when

def get_spot_price(asset) -> float:
    if asset.kind == "crypto":
        return _binance_spot(asset.binance_symbol)
    if asset.kind == "stock":
        return _yf_spot(asset.yf_symbol)
    raise ValueError(f"unsupported asset kind for pricing: {asset.kind}")

def get_historical_price(asset, when: datetime) -> float:
    if asset.kind == "crypto":
        return _binance_historical(asset.binance_symbol, when)
    if asset.kind == "stock":
        return _yf_historical(asset.yf_symbol, when)
    raise ValueError(f"unsupported asset kind for pricing: {asset.kind}")
```

> Uwaga (akcje): poza sesją giełdową `_yf_historical` zwraca najbliższy dostępny close — to akceptowalna prawda gruntowa dla horyzontów 24h/7d. Dla 1h na akcji poza sesją outcome może być mało znaczący — w Fazie 1 akceptujemy, w 1.5 ew. pomijamy 1h dla `kind=stock`.

- [ ] **Step 4: Run → PASS** — `cd argus && pytest tests/test_prices.py -v`

- [ ] **Step 5: Commit** — `git add argus/argus/prices.py argus/tests/test_prices.py && git commit -m "feat(argus): price module (binance crypto + yfinance stock)"`

---

### Task 5: Inline regex claim extractor

**Files:**
- Create: `argus/argus/extract.py`
- Test: `argus/tests/test_extract.py`

- [ ] **Step 1: Test**

```python
from argus.extract import extract_claims, PARSER_VERSION
from argus.models import Asset

ASSETS = [Asset(symbol="BTC", kind="crypto"), Asset(symbol="ETH", kind="crypto"),
          Asset(symbol="SOL", kind="crypto")]

def test_long_is_bull_high_conf():
    c = extract_claims("Going long BTC, target 100k", ASSETS)
    assert len(c) == 1
    assert c[0].asset_symbol == "BTC"
    assert c[0].direction == "bull"
    assert c[0].confidence >= 0.7
    assert c[0].target_price == 100000.0

def test_bearish_is_bear_low_conf():
    c = extract_claims("I'm a bit bearish on ETH maybe", ASSETS)
    assert c[0].direction == "bear"
    assert c[0].confidence <= 0.5

def test_short_keyword():
    c = extract_claims("short SOL here", ASSETS)
    assert c[0].direction == "bear"

def test_no_asset_no_claim():
    assert extract_claims("market looks interesting today", ASSETS) == []

def test_no_direction_no_claim():
    assert extract_claims("BTC is a cryptocurrency", ASSETS) == []

def test_parser_version_constant():
    assert PARSER_VERSION == "rule-v1"
```

- [ ] **Step 2: Run → FAIL** (ImportError).

- [ ] **Step 3: `argus/extract.py`**

```python
import re
from dataclasses import dataclass

PARSER_VERSION = "rule-v1"

@dataclass
class ParsedClaim:
    asset_symbol: str
    direction: str       # bull|bear|neutral
    confidence: float    # 0..1
    target_price: float | None = None

# (regex, direction, confidence) — kolejność = priorytet (mocniejsze wzorce wyżej)
_PATTERNS = [
    (r"\blong\b", "bull", 0.8),
    (r"\bshort\b", "bear", 0.8),
    (r"\bbullish\b", "bull", 0.6),
    (r"\bbearish\b", "bear", 0.6),
    (r"\bpump(s|ing|ed)?\b", "bull", 0.5),
    (r"\bdump(s|ing|ed)?\b", "bear", 0.5),
]
_HEDGE = re.compile(r"\b(maybe|might|could|a bit|slightly|imo)\b", re.I)
_TARGET = re.compile(r"target\s*\$?([0-9][0-9.,]*)\s*([kKmM]?)")

def _parse_target(text: str) -> float | None:
    m = _TARGET.search(text)
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    unit = m.group(2).lower()
    return num * {"k": 1_000, "m": 1_000_000, "": 1}[unit]

def extract_claims(text: str, assets) -> list[ParsedClaim]:
    low = text.lower()
    symbols = [a.symbol for a in assets if a.symbol.lower() in re.findall(r"[a-z0-9.]+", low)]
    if not symbols:
        return []
    direction = None
    confidence = 0.0
    for pat, d, conf in _PATTERNS:
        if re.search(pat, low):
            direction, confidence = d, conf
            break
    if direction is None:
        return []
    if _HEDGE.search(text):
        confidence = max(0.2, confidence - 0.4)
    target = _parse_target(text)
    return [ParsedClaim(asset_symbol=s, direction=direction,
                        confidence=round(confidence, 2), target_price=target)
            for s in symbols]
```

- [ ] **Step 4: Run → PASS** — `cd argus && pytest tests/test_extract.py -v`

- [ ] **Step 5: Commit** — `git add argus/argus/extract.py argus/tests/test_extract.py && git commit -m "feat(argus): rule-v1 inline regex claim extractor"`

---

### Task 6: RSS collector

**Files:**
- Create: `argus/argus/collectors/__init__.py` (pusty), `argus/argus/collectors/rss.py`
- Test: `argus/tests/test_rss.py`

- [ ] **Step 1: Test (mock feedparser + prices)**

```python
from datetime import datetime, timezone
from unittest.mock import patch
from types import SimpleNamespace
from argus.models import Asset, Source, Item, Claim, ClaimAudit
from argus.collectors.rss import collect_rss

def _fake_feed():
    e = SimpleNamespace(id="e1", title="Going long BTC target 100k",
                        summary="bullish", link="http://x/1",
                        published_parsed=(2026, 6, 1, 0, 0, 0, 0, 0, 0))
    return SimpleNamespace(entries=[e])

def test_collect_creates_item_claim_audit(session):
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    src = Source(kind="rss", handle="http://feed", display_name="F")
    session.add(src); session.commit()
    with patch("argus.collectors.rss.feedparser.parse", return_value=_fake_feed()), \
         patch("argus.collectors.rss.get_spot_price", return_value=67000.0):
        n = collect_rss(session, src)
    assert n == 1
    assert session.query(Item).count() == 1
    c = session.query(Claim).one()
    assert c.asset == "BTC" and c.direction == "bull" and c.entry_price == 67000.0
    assert session.query(ClaimAudit).one().parser_version == "rule-v1"

def test_collect_dedup(session):
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    src = Source(kind="rss", handle="http://feed", display_name="F")
    session.add(src); session.commit()
    with patch("argus.collectors.rss.feedparser.parse", return_value=_fake_feed()), \
         patch("argus.collectors.rss.get_spot_price", return_value=67000.0):
        collect_rss(session, src)
        collect_rss(session, src)  # ten sam external_id
    assert session.query(Item).count() == 1
```

- [ ] **Step 2: Run → FAIL** (ImportError).

- [ ] **Step 3: `argus/collectors/rss.py`**

```python
from datetime import datetime, timezone
import calendar
import feedparser
from sqlalchemy import select
from argus.models import Asset, Item, Claim, ClaimAudit
from argus.extract import extract_claims, PARSER_VERSION
from argus.prices import get_spot_price
from dataclasses import asdict

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
            entry_price = get_spot_price(asset)
            claim = Claim(source_id=source.id, item_id=item.id, asset=asset.symbol,
                          direction=pc.direction, target_price=pc.target_price,
                          confidence=pc.confidence, method="rule",
                          entry_price=entry_price, entry_ts=now, status="open")
            session.add(claim); session.flush()
            session.add(ClaimAudit(claim_id=claim.id, raw_text=text,
                                   parsed_claim=asdict(pc), parser_version=PARSER_VERSION))
    session.commit()
    return created
```

- [ ] **Step 4: Run → PASS** — `cd argus && pytest tests/test_rss.py -v`

- [ ] **Step 5: Commit** — `git add argus/argus/collectors/ argus/tests/test_rss.py && git commit -m "feat(argus): RSS collector with dedup + claim creation"`

---

### Task 7: Outcome evaluator

**Files:**
- Create: `argus/argus/evaluator.py`
- Test: `argus/tests/test_evaluator.py`

- [ ] **Step 1: Test (logika hit dla bull/bear/neutral + progi)**

```python
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from argus.models import Asset, Source, Claim, Outcome
from argus.evaluator import evaluate_due_claims, HORIZONS, THRESHOLDS

def _setup(session, direction, entry=100.0):
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    s = Source(kind="rss", handle="h", display_name="D"); session.add(s); session.flush()
    old = datetime.now(timezone.utc) - timedelta(days=8)  # po wszystkich horyzontach
    c = Claim(source_id=s.id, asset="BTC", direction=direction, confidence=0.8,
              method="rule", entry_price=entry, entry_ts=old, status="open")
    session.add(c); session.commit()
    return c

def test_bull_hit_when_price_up(session):
    _setup(session, "bull")
    with patch("argus.evaluator.get_historical_price", return_value=110.0):
        evaluate_due_claims(session, datetime.now(timezone.utc))
    outs = {o.horizon: o for o in session.query(Outcome).all()}
    assert set(outs) == set(HORIZONS)
    assert all(o.hit for o in outs.values())          # +10% > każdy próg
    assert abs(outs["24h"].return_pct - 0.10) < 1e-6

def test_bear_hit_when_price_down(session):
    _setup(session, "bear")
    with patch("argus.evaluator.get_historical_price", return_value=90.0):
        evaluate_due_claims(session, datetime.now(timezone.utc))
    assert all(o.hit for o in session.query(Outcome).all())

def test_neutral_hit_when_flat(session):
    _setup(session, "neutral")
    with patch("argus.evaluator.get_historical_price", return_value=100.1):
        evaluate_due_claims(session, datetime.now(timezone.utc))
    assert all(o.hit for o in session.query(Outcome).all())  # 0.1% < każdy próg

def test_no_double_eval(session):
    _setup(session, "bull")
    with patch("argus.evaluator.get_historical_price", return_value=110.0):
        evaluate_due_claims(session, datetime.now(timezone.utc))
        evaluate_due_claims(session, datetime.now(timezone.utc))
    assert session.query(Outcome).count() == len(HORIZONS)
```

- [ ] **Step 2: Run → FAIL** (ImportError).

- [ ] **Step 3: `argus/evaluator.py`**

```python
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from argus.models import Asset, Claim, Outcome
from argus.prices import get_historical_price

HORIZONS = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7)}
THRESHOLDS = {"1h": 0.005, "24h": 0.015, "7d": 0.04}

def _hit(direction: str, ret: float, thr: float) -> bool:
    if direction == "bull":
        return ret >= thr
    if direction == "bear":
        return ret <= -thr
    return abs(ret) < thr  # neutral

def evaluate_due_claims(session, now: datetime) -> int:
    claims = list(session.scalars(select(Claim).where(Claim.status != "closed")))
    assets = {a.symbol: a for a in session.scalars(select(Asset))}
    done = {(o.claim_id, o.horizon) for o in session.scalars(select(Outcome))}
    created = 0
    for c in claims:
        asset = assets.get(c.asset)
        if asset is None or not asset.scorable:
            continue
        for h, delta in HORIZONS.items():
            if (c.id, h) in done:
                continue
            if now < c.entry_ts + delta:
                continue
            price = get_historical_price(asset, c.entry_ts + delta)
            ret = (price - c.entry_price) / c.entry_price
            session.add(Outcome(claim_id=c.id, horizon=h, eval_ts=now,
                                price_at_horizon=price, return_pct=ret,
                                hit=_hit(c.direction, ret, THRESHOLDS[h]),
                                resolved_at=now))
            created += 1
        # zamknij claim gdy wszystkie horyzonty rozliczone
        if now >= c.entry_ts + HORIZONS["7d"]:
            c.status = "closed"
    session.commit()
    return created
```

- [ ] **Step 4: Run → PASS** — `cd argus && pytest tests/test_evaluator.py -v`

- [ ] **Step 5: Commit** — `git add argus/argus/evaluator.py argus/tests/test_evaluator.py && git commit -m "feat(argus): outcome evaluator (1h/24h/7d hit logic)"`

---

### Task 8: Source scorer

**Files:**
- Create: `argus/argus/scorer.py`
- Test: `argus/tests/test_scorer.py`

- [ ] **Step 1: Test (formuła decayed_score + agregaty)**

```python
from datetime import datetime, timedelta, timezone
from argus.models import Source, Claim, Outcome, SourceAssetScore, SourceScore
from argus.scorer import recompute_scores

def _claim_with_outcome(session, source_id, asset, hit, ret, age_days=0):
    ts = datetime.now(timezone.utc) - timedelta(days=age_days)
    c = Claim(source_id=source_id, asset=asset, direction="bull", confidence=0.8,
              method="rule", entry_price=100.0, entry_ts=ts, status="closed")
    session.add(c); session.flush()
    session.add(Outcome(claim_id=c.id, horizon="24h", eval_ts=ts,
                        price_at_horizon=100*(1+ret), return_pct=ret, hit=hit))
    session.commit()

def test_perfect_source_high_score(session):
    s = Source(kind="rss", handle="h", display_name="D"); session.add(s); session.commit()
    for _ in range(10):
        _claim_with_outcome(session, s.id, "BTC", hit=True, ret=0.05)
    recompute_scores(session)
    sas = session.query(SourceAssetScore).filter_by(asset="BTC", horizon="24h").one()
    assert sas.n_claims == 10 and sas.n_hits == 10
    assert sas.hit_rate == 1.0
    assert sas.decayed_score > 0.8           # Beta prior nie ściąga zbyt mocno przy n=10
    assert abs(sas.avg_return - 0.05) < 1e-6

def test_small_sample_shrinks_to_half(session):
    s = Source(kind="rss", handle="h2", display_name="D2"); session.add(s); session.commit()
    _claim_with_outcome(session, s.id, "ETH", hit=True, ret=0.05)  # n=1
    recompute_scores(session)
    sas = session.query(SourceAssetScore).filter_by(asset="ETH", horizon="24h").one()
    assert 0.5 < sas.decayed_score < 0.8     # prior ściąga małą próbkę w stronę 0.5

def test_rollup_source_score_exists(session):
    s = Source(kind="rss", handle="h3", display_name="D3"); session.add(s); session.commit()
    _claim_with_outcome(session, s.id, "BTC", hit=True, ret=0.05)
    _claim_with_outcome(session, s.id, "ETH", hit=False, ret=-0.05)
    recompute_scores(session)
    assert session.query(SourceScore).filter_by(source_id=s.id, horizon="24h").count() == 1
```

- [ ] **Step 2: Run → FAIL** (ImportError).

- [ ] **Step 3: `argus/scorer.py`**

```python
import math
from datetime import datetime, timezone
from collections import defaultdict
from sqlalchemy import select, delete
from argus.models import Claim, Outcome, SourceAssetScore, SourceScore

def recompute_scores(session, *, tau_days: float = 14, alpha: float = 2,
                     beta: float = 2, k_min: int = 5) -> None:
    now = datetime.now(timezone.utc)
    # claim_id -> (source_id, asset, entry_ts)
    claims = {c.id: c for c in session.scalars(select(Claim))}
    # grupuj outcomes po (source, asset, horizon)
    groups = defaultdict(list)   # key -> list[(hit, ret, age_days)]
    for o in session.scalars(select(Outcome)):
        c = claims.get(o.claim_id)
        if c is None:
            continue
        age = (now - c.entry_ts).total_seconds() / 86400.0
        groups[(c.source_id, c.asset, o.horizon)].append((o.hit, o.return_pct, age))

    session.execute(delete(SourceAssetScore))
    session.execute(delete(SourceScore))

    # rollup akumulatory per (source, horizon)
    roll = defaultdict(lambda: {"n": 0, "hits": 0, "ret_sum": 0.0,
                                "w_sum": 0.0, "wh_sum": 0.0})

    for (sid, asset, horizon), rows in groups.items():
        n = len(rows)
        hits = sum(1 for hit, _, _ in rows if hit)
        ret_sum = sum(r for _, r, _ in rows)
        w_sum = sum(math.exp(-age / tau_days) for _, _, age in rows)
        wh_sum = sum(math.exp(-age / tau_days) for hit, _, age in rows if hit)
        decayed = (wh_sum + alpha) / (w_sum + alpha + beta)
        session.add(SourceAssetScore(
            source_id=sid, asset=asset, horizon=horizon, n_claims=n, n_hits=hits,
            hit_rate=hits / n, avg_return=ret_sum / n, decayed_score=decayed,
            updated_at=now))
        r = roll[(sid, horizon)]
        r["n"] += n; r["hits"] += hits; r["ret_sum"] += ret_sum
        r["w_sum"] += w_sum; r["wh_sum"] += wh_sum

    for (sid, horizon), r in roll.items():
        decayed = (r["wh_sum"] + alpha) / (r["w_sum"] + alpha + beta)
        session.add(SourceScore(
            source_id=sid, horizon=horizon, n_claims=r["n"],
            hit_rate=r["hits"] / r["n"], avg_return=r["ret_sum"] / r["n"],
            decayed_score=decayed, updated_at=now))
    session.commit()
```

- [ ] **Step 4: Run → PASS** — `cd argus && pytest tests/test_scorer.py -v`

- [ ] **Step 5: Commit** — `git add argus/argus/scorer.py argus/tests/test_scorer.py && git commit -m "feat(argus): source scorer (decayed Bayesian credibility + rollup)"`

---

### Task 9: Trend-lean analytics

**Files:**
- Create: `argus/argus/analytics.py`
- Test: `argus/tests/test_analytics.py`

- [ ] **Step 1: Test**

```python
from datetime import datetime, timezone
from argus.models import Asset, Source, Claim, SourceAssetScore
from argus.analytics import trend_lean

def test_lean_weighted_by_credibility_and_confidence(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True))
    s = Source(kind="rss", handle="h", display_name="D"); session.add(s); session.flush()
    now = datetime.now(timezone.utc)
    # aktywny (open) byczy claim
    session.add(Claim(source_id=s.id, asset="BTC", direction="bull", confidence=0.8,
                      method="rule", entry_price=100.0, entry_ts=now, status="open"))
    session.add(SourceAssetScore(source_id=s.id, asset="BTC", horizon="24h",
                                 n_claims=10, n_hits=8, hit_rate=0.8, avg_return=0.03,
                                 decayed_score=0.75, updated_at=now))
    session.commit()
    rows = trend_lean(session, "24h")
    btc = next(r for r in rows if r["asset"] == "BTC")
    assert btc["lean"] > 0                       # byczy
    assert abs(btc["lean"] - (0.75 * 0.8)) < 0.05  # ~ score*confidence*freshness(~1)

def test_closed_claims_excluded(session):
    session.add(Asset(symbol="ETH", kind="crypto", scorable=True))
    s = Source(kind="rss", handle="h2", display_name="D2"); session.add(s); session.flush()
    now = datetime.now(timezone.utc)
    session.add(Claim(source_id=s.id, asset="ETH", direction="bull", confidence=0.9,
                      method="rule", entry_price=100.0, entry_ts=now, status="closed"))
    session.commit()
    rows = trend_lean(session, "24h")
    assert all(r["asset"] != "ETH" for r in rows)
```

- [ ] **Step 2: Run → FAIL** (ImportError).

- [ ] **Step 3: `argus/analytics.py`**

```python
import math
from datetime import datetime, timezone
from collections import defaultdict
from sqlalchemy import select
from argus.models import Claim, SourceAssetScore, SourceScore

def trend_lean(session, horizon: str, *, tau_days: float = 7) -> list[dict]:
    now = datetime.now(timezone.utc)
    sas = {(s.source_id, s.asset): s.decayed_score
           for s in session.scalars(select(SourceAssetScore).where(SourceAssetScore.horizon == horizon))}
    src = {s.source_id: s.decayed_score
           for s in session.scalars(select(SourceScore).where(SourceScore.horizon == horizon))}
    agg = defaultdict(float)
    for c in session.scalars(select(Claim).where(Claim.status == "open")):
        score = sas.get((c.source_id, c.asset), src.get(c.source_id, 0.5))
        freshness = math.exp(-((now - c.entry_ts).total_seconds() / 86400.0) / tau_days)
        sign = {"bull": 1, "bear": -1, "neutral": 0}[c.direction]
        agg[c.asset] += sign * score * c.confidence * freshness
    return [{"asset": a, "lean": round(v, 4)} for a, v in sorted(agg.items())]
```

- [ ] **Step 4: Run → PASS** — `cd argus && pytest tests/test_analytics.py -v`

- [ ] **Step 5: Commit** — `git add argus/argus/analytics.py argus/tests/test_analytics.py && git commit -m "feat(argus): trend-lean weighted by source credibility"`

---

### Task 10: FastAPI JSON API + static mount

**Files:**
- Create: `argus/argus/api.py`
- Test: `argus/tests/test_api.py`

- [ ] **Step 1: Test (TestClient, DI override sesji)**

```python
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from argus.db import Base
import argus.models  # noqa
from argus.models import Asset, Source, SourceScore
from argus.api import app, get_session

def _client():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    def override():
        s = Sess()
        try: yield s
        finally: s.close()
    app.dependency_overrides[get_session] = override
    return TestClient(app), Sess

def test_health():
    client, _ = _client()
    assert client.get("/health").json() == {"status": "ok"}

def test_assets_and_sources_endpoints():
    client, Sess = _client()
    s = Sess()
    s.add(Asset(symbol="BTC", kind="crypto", scorable=True))
    src = Source(kind="rss", handle="h", display_name="CoinDesk"); s.add(src); s.flush()
    s.add(SourceScore(source_id=src.id, horizon="24h", n_claims=5, hit_rate=0.6,
                      avg_return=0.02, decayed_score=0.58,
                      updated_at=datetime.now(timezone.utc)))
    s.commit()
    assert client.get("/api/assets?horizon=24h").status_code == 200
    leaders = client.get("/api/sources?horizon=24h").json()
    assert leaders[0]["display_name"] == "CoinDesk"
    assert leaders[0]["decayed_score"] == 0.58
```

- [ ] **Step 2: Run → FAIL** (ImportError).

- [ ] **Step 3: `argus/api.py`**

```python
from pathlib import Path
from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from argus.db import SessionLocal
from argus.models import Source, SourceScore, Claim, Outcome
from argus.analytics import trend_lean

app = FastAPI(title="Argus")

def get_session():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/api/assets")
def assets(horizon: str = "24h", session=Depends(get_session)):
    return trend_lean(session, horizon)

@app.get("/api/sources")
def sources(horizon: str = "24h", session=Depends(get_session)):
    rows = session.execute(
        select(Source, SourceScore)
        .join(SourceScore, SourceScore.source_id == Source.id)
        .where(SourceScore.horizon == horizon)
        .order_by(SourceScore.decayed_score.desc())
    ).all()
    return [{"display_name": s.display_name, "kind": s.kind,
             "n_claims": sc.n_claims, "hit_rate": sc.hit_rate,
             "avg_return": sc.avg_return, "decayed_score": sc.decayed_score}
            for s, sc in rows]

@app.get("/api/claims")
def claims(limit: int = 50, session=Depends(get_session)):
    rows = session.scalars(select(Claim).order_by(Claim.entry_ts.desc()).limit(limit))
    return [{"id": c.id, "asset": c.asset, "direction": c.direction,
             "confidence": c.confidence, "method": c.method,
             "entry_ts": c.entry_ts.isoformat(), "status": c.status} for c in rows]

# static dashboard (Task 12)
_web = Path(__file__).parent / "web"
if _web.exists():
    app.mount("/", StaticFiles(directory=str(_web), html=True), name="web")
```

- [ ] **Step 4: Run → PASS** — `cd argus && pytest tests/test_api.py -v`

- [ ] **Step 5: Commit** — `git add argus/argus/api.py argus/tests/test_api.py && git commit -m "feat(argus): FastAPI JSON API (assets/sources/claims/health)"`

---

### Task 11: Scheduler — interfejs + APScheduler impl

**Files:**
- Create: `argus/argus/scheduler/__init__.py` (pusty), `argus/argus/scheduler/base.py`, `argus/argus/scheduler/apscheduler_impl.py`
- Test: `argus/tests/test_scheduler.py`

- [ ] **Step 1: Test (interfejs: rejestracja + listowanie jobów, bez realnego czasu)**

```python
from argus.scheduler.apscheduler_impl import APScheduler

def test_register_and_list_jobs():
    sched = APScheduler()
    sched.add_interval("rss", lambda: None, minutes=30)
    sched.add_interval("evaluate", lambda: None, minutes=60)
    assert set(sched.list_jobs()) == {"rss", "evaluate"}

def test_run_now_executes(monkeypatch):
    calls = []
    sched = APScheduler()
    sched.add_interval("x", lambda: calls.append(1), minutes=5)
    sched.run_now("x")
    assert calls == [1]
```

- [ ] **Step 2: Run → FAIL** (ImportError).

- [ ] **Step 3: `argus/scheduler/base.py`**

```python
from abc import ABC, abstractmethod
from typing import Callable

class Scheduler(ABC):
    @abstractmethod
    def add_interval(self, name: str, fn: Callable[[], None], *, minutes: int) -> None: ...
    @abstractmethod
    def list_jobs(self) -> list[str]: ...
    @abstractmethod
    def run_now(self, name: str) -> None: ...
    @abstractmethod
    def start(self) -> None: ...
```

- [ ] **Step 4: `argus/scheduler/apscheduler_impl.py`**

```python
from typing import Callable
from apscheduler.schedulers.background import BackgroundScheduler
from argus.scheduler.base import Scheduler

class APScheduler(Scheduler):
    def __init__(self):
        self._sched = BackgroundScheduler(timezone="UTC")
        self._fns: dict[str, Callable[[], None]] = {}

    def add_interval(self, name, fn, *, minutes):
        self._fns[name] = fn
        self._sched.add_job(fn, "interval", minutes=minutes, id=name, replace_existing=True)

    def list_jobs(self):
        return list(self._fns.keys())

    def run_now(self, name):
        self._fns[name]()

    def start(self):
        self._sched.start()
```

- [ ] **Step 5: Run → PASS** — `cd argus && pytest tests/test_scheduler.py -v`

- [ ] **Step 6: Commit** — `git add argus/argus/scheduler/ argus/tests/test_scheduler.py && git commit -m "feat(argus): scheduler interface + APScheduler impl"`

---

### Task 12: Minimalny statyczny dashboard

**Files:**
- Create: `argus/argus/web/index.html`, `argus/argus/web/app.js`

(UI cienka warstwa nad API z Task 10 — weryfikacja manualna + smoke w Task 13. Pełny React: późniejsza faza.)

- [ ] **Step 1: `argus/web/index.html`**

```html
<!doctype html>
<html lang="pl"><head><meta charset="utf-8"><title>Argus</title>
<style>body{font-family:system-ui;margin:2rem;background:#0f1115;color:#e6e6e6}
table{border-collapse:collapse;margin-bottom:2rem;width:100%}
th,td{border:1px solid #2a2e37;padding:.4rem .6rem;text-align:left}
.bull{color:#3fb950}.bear{color:#f85149}</style></head>
<body>
<h1>Argus — trend credibility</h1>
<label>Horyzont:
  <select id="h"><option>1h</option><option selected>24h</option><option>7d</option></select>
</label>
<h2>Trend-lean (aktywa)</h2><table id="assets"></table>
<h2>Ranking źródeł</h2><table id="sources"></table>
<h2>Ostatnie twierdzenia</h2><table id="claims"></table>
<script src="app.js"></script>
</body></html>
```

- [ ] **Step 2: `argus/web/app.js`**

```javascript
async function load() {
  const h = document.getElementById('h').value;
  const assets = await (await fetch(`/api/assets?horizon=${h}`)).json();
  document.getElementById('assets').innerHTML =
    '<tr><th>Asset</th><th>Lean</th></tr>' + assets.map(a =>
      `<tr><td>${a.asset}</td><td class="${a.lean>=0?'bull':'bear'}">${a.lean}</td></tr>`).join('');
  const sources = await (await fetch(`/api/sources?horizon=${h}`)).json();
  document.getElementById('sources').innerHTML =
    '<tr><th>Źródło</th><th>n</th><th>hit%</th><th>score</th></tr>' + sources.map(s =>
      `<tr><td>${s.display_name}</td><td>${s.n_claims}</td><td>${(s.hit_rate*100).toFixed(0)}</td><td>${s.decayed_score.toFixed(2)}</td></tr>`).join('');
  const claims = await (await fetch('/api/claims?limit=30')).json();
  document.getElementById('claims').innerHTML =
    '<tr><th>Asset</th><th>Dir</th><th>Conf</th><th>Kiedy</th><th>Status</th></tr>' + claims.map(c =>
      `<tr><td>${c.asset}</td><td class="${c.direction==='bull'?'bull':'bear'}">${c.direction}</td><td>${c.confidence}</td><td>${c.entry_ts.slice(0,16)}</td><td>${c.status}</td></tr>`).join('');
}
document.getElementById('h').addEventListener('change', load);
load();
```

- [ ] **Step 3: Commit** — `git add argus/argus/web/ && git commit -m "feat(argus): minimal static dashboard"`

---

### Task 13: Docker + compose + main wiring + smoke

**Files:**
- Create: `argus/argus/main.py`, `argus/Dockerfile`, `argus/docker-compose.yml`

- [ ] **Step 1: `argus/argus/main.py`** (entrypoint: seed + scheduler + uvicorn)

```python
import uvicorn
from argus.db import Base, engine, SessionLocal
import argus.models  # noqa
from argus.config import settings
from argus.seed import seed_assets, seed_sources
from argus.collectors.rss import collect_rss
from argus.evaluator import evaluate_due_claims
from argus.scorer import recompute_scores
from argus.scheduler.apscheduler_impl import APScheduler
from argus.models import Source
from sqlalchemy import select
from datetime import datetime, timezone

def _rss_job():
    with SessionLocal() as s:
        for src in s.scalars(select(Source).where(Source.kind == "rss", Source.active == True)):  # noqa: E712
            collect_rss(s, src)

def _eval_job():
    with SessionLocal() as s:
        evaluate_due_claims(s, datetime.now(timezone.utc))

def _score_job():
    with SessionLocal() as s:
        recompute_scores(s)

def bootstrap():
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_assets(s, settings.watchlist_path)
        seed_sources(s, settings.sources_path)
    sched = APScheduler()
    sched.add_interval("rss", _rss_job, minutes=30)
    sched.add_interval("evaluate", _eval_job, minutes=60)
    sched.add_interval("score", _score_job, minutes=360)
    sched.start()

if __name__ == "__main__":
    bootstrap()
    uvicorn.run("argus.api:app", host="0.0.0.0", port=8080)
```

- [ ] **Step 2: `argus/Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY argus ./argus
COPY config ./config
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "argus.main"]
```

- [ ] **Step 3: `argus/docker-compose.yml`**

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: argus
      POSTGRES_PASSWORD: argus
      POSTGRES_DB: argus
    volumes: ["argus-pg:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U argus"]
      interval: 5s
      retries: 10
  app:
    build: .
    env_file: .env
    depends_on:
      db: {condition: service_healthy}
    ports: ["8080:8080"]
volumes:
  argus-pg:
```

- [ ] **Step 4: Smoke test (manualny)**

```bash
cd argus
cp .env.example .env
docker compose up -d --build
sleep 20
curl -sS http://localhost:8080/health           # → {"status":"ok"}
curl -sS "http://localhost:8080/api/assets?horizon=24h"   # → [] na starcie, potem dane
docker compose logs app | tail -30               # brak tracebacków, scheduler wystartował
```
Expected: `/health` zwraca ok; po pierwszym przejściu `rss` joba w `claims` pojawiają się wiersze (sprawdź `curl .../api/claims`).

- [ ] **Step 5: Commit** — `git add argus/argus/main.py argus/Dockerfile argus/docker-compose.yml && git commit -m "feat(argus): docker compose + main wiring + smoke"`

---

## Self-Review (wykonane)

**Spec coverage:**
- Pełny cykl claim→outcome→score→ranking → Tasks 5–9 ✅
- source_asset_scores (per źródło+aktywo) → Task 8 ✅
- claim_audit od dnia 1 → Task 2 + Task 6 ✅
- claim_weight = score×confidence×freshness → Task 9 ✅
- trend-lean z siłą sygnału → Task 9 ✅
- horyzonty 1h/24h/7d + progi → Task 7 ✅
- scheduler za interfejsem → Task 11 ✅
- local Postgres (prod) / SQLite (test) za SQLAlchemy → Task 1, 13 ✅
- prices on-demand (entry spot + historical) → Task 4 ✅
- crypto (Binance) + stock (yfinance) provider → Task 4 ✅
- watchlist seed (krypto scorable, akcje scorable, indeksy nie) → Task 0, 3 ✅
- minimalny dashboard → Task 12 ✅
- Faza 0 spike (Hyperdash/Coinglass) → Task 0 ✅
- bez LLM, bez transakcji, bez multi-agent → cały plan zgodny ✅

**Poza zakresem tego planu (świadomie):** Hyperdash collector (Faza 1.5), LLM router/ekstrakcja (Faza 2), Reddit/Coinglass overlay/alerty/digest (Faza 3), pełny React SPA.

**Placeholder scan:** brak TODO/TBD w krokach kodowych; jedyne `VERIFY_IN_STEP_2` w watchlist.yaml to celowy marker rozwiązywany w Task 0 Step 2.

**Type consistency:** `direction`/`method`/`horizon` wartości spójne; `get_spot_price`/`get_historical_price`/`extract_claims`/`recompute_scores`/`trend_lean`/`evaluate_due_claims` sygnatury zgodne między zadaniami i sekcją Konwencje.
