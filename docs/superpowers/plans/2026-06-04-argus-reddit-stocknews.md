# Argus Increment 4 — Reddit + Stock-News + Sector Association Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zwiększyć recall claimów: dodać Reddit + stock-news jako feedy RSS i asocjację sektorową (sygnał o sektorze → ticker z niskim confidence), bez nowego kolektora i bez LLM.

**Architecture:** Rozszerzamy `extract.py` do `rule-v2` (slang WSB + cashtagi + `sector_map`), dodajemy feedy do `config/sources.yaml` (kind `reddit`/`news`) i nową `config/sectors.yaml` (aliasy→tickery). `collect_rss` ładuje sector_map i przekazuje do ekstraktora. `_rss_job` poszerzony na kind reddit/news. Bez nowych tabel/endpointów.

**Tech Stack:** Python 3.12, feedparser, pyyaml, pytest. Testy w Dockerze (brak python na hoście Windows).

**Spec:** `docs/superpowers/specs/2026-06-04-argus-reddit-stocknews-design.md`

---

## Konwencje
- **Brak lokalnego pythona.** Testy w Dockerze (PowerShell; trusted-host przez proxy SSL):
  ```
  docker run --rm -v "C:/Users/DAMA/Documents/docker/n8n/argus:/app" -w /app -v argus-pipcache:/root/.cache/pip -e PYTHONPATH=/app python:3.12-slim sh -c "pip install -q --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt && python -m pytest -q <ŚCIEŻKA>"
  ```
- `extract_claims(text, assets, sector_map=None) -> list[ParsedClaim]`. `sector_map` = `{sector_key: {"aliases":[str], "tickers":[str], "confidence":float}}`.
- `load_sector_map(path="config/sectors.yaml") -> dict`.

## Struktura plików
```
argus/argus/extract.py          # MOD — Task 1 (rule-v2 + sector_map)
argus/config/sources.yaml       # MOD — Task 2 (+ reddit/news feeds)
argus/config/sectors.yaml       # NOWY — Task 2
argus/argus/collectors/rss.py   # MOD — Task 3 (load+pass sector_map)
argus/argus/main.py             # MOD — Task 4 (_rss_job kind filter)
argus/tests/test_extract.py     # MOD — Task 1
argus/tests/test_config.py      # NOWY — Task 2
argus/tests/test_rss.py         # MOD — Task 3
```

---

### Task 1: `extract.py` → rule-v2 (slang + cashtagi + sector_map)

**Files:** Modify `argus/argus/extract.py`; Modify `argus/tests/test_extract.py`

- [ ] **Step 1: Update + append tests in `argus/tests/test_extract.py`**
Change the existing `test_parser_version_constant` assertion to `"rule-v2"`:
```python
def test_parser_version_constant():
    assert PARSER_VERSION == "rule-v2"
```
Append new tests (the existing `ASSETS` has BTC/ETH/SOL; these define their own where needed):
```python
STOCKS = [Asset(symbol="NFE", kind="stock"), Asset(symbol="DLNG", kind="stock"),
          Asset(symbol="BTC", kind="crypto")]

def test_calls_is_bull():
    c = extract_claims("loading $NFE calls", STOCKS)
    assert c[0].asset_symbol == "NFE" and c[0].direction == "bull"

def test_puts_is_bear():
    c = extract_claims("buying $NFE puts here", STOCKS)
    assert c[0].direction == "bear"

def test_short_squeeze_is_bull_not_bear():
    c = extract_claims("massive short squeeze on BTC", ASSETS)
    assert c[0].asset_symbol == "BTC" and c[0].direction == "bull"

def test_bloodbath_is_bear():
    c = extract_claims("ETH bloodbath today", ASSETS)
    assert c[0].direction == "bear"

def test_cashtag_with_punctuation():
    assert extract_claims("($NFE) calls", STOCKS)[0].asset_symbol == "NFE"
    assert extract_claims("$NFE.. mooning", STOCKS)[0].asset_symbol == "NFE"

def test_sector_association_low_confidence():
    smap = {"natural_gas": {"aliases": ["natural gas", "lng"], "tickers": ["NFE", "DLNG"], "confidence": 0.3}}
    out = extract_claims("natural gas looking bullish", STOCKS, sector_map=smap)
    by = {c.asset_symbol: c for c in out}
    assert set(by) == {"NFE", "DLNG"}
    assert by["NFE"].direction == "bull" and by["NFE"].confidence == 0.3

def test_direct_beats_sector_no_dup():
    smap = {"natural_gas": {"aliases": ["natural gas"], "tickers": ["NFE", "DLNG"], "confidence": 0.3}}
    out = extract_claims("$NFE calls — natural gas bullish", STOCKS, sector_map=smap)
    nfe = [c for c in out if c.asset_symbol == "NFE"]
    assert len(nfe) == 1 and nfe[0].confidence > 0.3      # direct confidence wins
    assert any(c.asset_symbol == "DLNG" and c.confidence == 0.3 for c in out)

def test_sector_only_no_direct_symbol():
    smap = {"natural_gas": {"aliases": ["natural gas"], "tickers": ["NFE", "DLNG"], "confidence": 0.3}}
    out = extract_claims("natural gas is dumping", STOCKS, sector_map=smap)
    assert {c.asset_symbol for c in out} == {"NFE", "DLNG"}
    assert all(c.direction == "bear" for c in out)
```

- [ ] **Step 2: Run, verify FAIL** — `... pytest -q tests/test_extract.py` → new tests fail (slang/sector/parser_version not present).

- [ ] **Step 3: Rewrite `argus/argus/extract.py`**
```python
import re
from dataclasses import dataclass

PARSER_VERSION = "rule-v2"

@dataclass
class ParsedClaim:
    asset_symbol: str
    direction: str       # bull|bear|neutral
    confidence: float    # 0..1
    target_price: float | None = None

# (regex, direction, confidence) — kolejność = priorytet (mocniejsze/jednoznaczne wyżej)
_PATTERNS = [
    (r"\bshort squeeze\b", "bull", 0.7),
    (r"\bgamma squeeze\b", "bull", 0.7),
    (r"\bsqueeze\b", "bull", 0.6),
    (r"\blong\b", "bull", 0.8),
    (r"\bshort\b", "bear", 0.8),
    (r"\bcalls?\b", "bull", 0.7),
    (r"\bputs\b", "bear", 0.7),
    (r"\bbullish\b", "bull", 0.6),
    (r"\bbearish\b", "bear", 0.6),
    (r"\bbreakout\b", "bull", 0.55),
    (r"\bmoonshot\b", "bull", 0.55),
    (r"\bmoon(ing|ed)?\b", "bull", 0.5),
    (r"🚀", "bull", 0.5),
    (r"\brip(s|ping|ped)?\b", "bull", 0.5),
    (r"\bsending\b", "bull", 0.5),
    (r"\bpump(s|ing|ed)?\b", "bull", 0.5),
    (r"\brug(\s*pull)?\b", "bear", 0.6),
    (r"\bbloodbath\b", "bear", 0.6),
    (r"\bmassacre\b", "bear", 0.6),
    (r"\bcapitulation\b", "bear", 0.6),
    (r"\brekt\b", "bear", 0.6),
    (r"\bdrilling\b", "bear", 0.55),
    (r"\bsell\s*off\b", "bear", 0.55),
    (r"\bcrash(ing|ed|es)?\b", "bear", 0.55),
    (r"\bdump(s|ing|ed)?\b", "bear", 0.5),
    (r"\bbuy\b", "bull", 0.4),
    (r"\bsell\b", "bear", 0.4),
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

def extract_claims(text: str, assets, sector_map: dict | None = None) -> list[ParsedClaim]:
    low = text.lower()
    tokens = set(re.findall(r"[a-z0-9]+", low))            # cashtag/punct-robust
    symbols = [a.symbol for a in assets if a.symbol.lower() in tokens]
    direction, confidence = None, 0.0
    for pat, d, conf in _PATTERNS:
        if re.search(pat, low):
            direction, confidence = d, conf
            break
    if direction is None:
        return []
    if _HEDGE.search(text):
        confidence = max(0.2, confidence - 0.4)
    target = _parse_target(text)
    claimed = set(symbols)
    out = [ParsedClaim(s, direction, round(confidence, 2), target) for s in symbols]
    if sector_map:
        known = {a.symbol for a in assets}
        for sec in sector_map.values():
            if any(alias.lower() in low for alias in sec.get("aliases", [])):
                sconf = round(float(sec.get("confidence", 0.3)), 2)
                for tk in sec.get("tickers", []):
                    if tk not in claimed and tk in known:
                        claimed.add(tk)
                        out.append(ParsedClaim(tk, direction, sconf, None))
    return out
```

- [ ] **Step 4: Run, verify PASS** — `... pytest -q tests/test_extract.py` → all green (existing + new). The previously-passing v1 tests still hold (long/bearish+hedge/short/no-direction).

- [ ] **Step 5: Commit**
```
git add argus/argus/extract.py argus/tests/test_extract.py
git commit -m "feat(argus): rule-v2 extractor (WSB slang + cashtags + sector association)"
```

---

### Task 2: Config — feeds (`sources.yaml`) + `sectors.yaml`

**Files:** Modify `argus/config/sources.yaml`; Create `argus/config/sectors.yaml`; Create `argus/tests/test_config.py`

- [ ] **Step 1: Write failing test `argus/tests/test_config.py`**
```python
import yaml

def test_sources_have_reddit_and_news():
    data = yaml.safe_load(open("config/sources.yaml", encoding="utf-8"))
    kinds = {s["kind"] for s in data["sources"]}
    assert {"rss", "reddit", "news"} <= kinds
    handles = [s["handle"] for s in data["sources"]]
    assert any("reddit.com" in h for h in handles)

def test_sectors_structure_and_known_tickers():
    data = yaml.safe_load(open("config/sectors.yaml", encoding="utf-8"))
    watchlist_stocks = {"XOMA", "BYND", "DLNG", "LCID", "NFE", "NTR", "PLG"}
    for key, sec in data.items():
        assert sec["aliases"] and sec["tickers"]
        assert isinstance(sec["confidence"], (int, float))
        assert set(sec["tickers"]) <= watchlist_stocks, f"{key} has unknown ticker"
```

- [ ] **Step 2: Run, verify FAIL** — `... pytest -q tests/test_config.py` → FileNotFound (sectors.yaml) / kinds missing.

- [ ] **Step 3a: Append to `argus/config/sources.yaml`** (keep existing 4 crypto RSS entries; add):
```yaml
  # --- Reddit (kind: reddit) ---
  - {kind: reddit, handle: "https://www.reddit.com/r/CryptoCurrency/.rss", display_name: "r/CryptoCurrency"}
  - {kind: reddit, handle: "https://www.reddit.com/r/CryptoMarkets/.rss",  display_name: "r/CryptoMarkets"}
  - {kind: reddit, handle: "https://www.reddit.com/r/SatoshiStreetBets/.rss", display_name: "r/SatoshiStreetBets"}
  - {kind: reddit, handle: "https://www.reddit.com/r/wallstreetbets/.rss", display_name: "r/wallstreetbets"}
  - {kind: reddit, handle: "https://www.reddit.com/r/stocks/.rss",         display_name: "r/stocks"}
  - {kind: reddit, handle: "https://www.reddit.com/r/StockMarket/.rss",    display_name: "r/StockMarket"}
  # --- Stock news (kind: news) ---
  - {kind: news, handle: "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",  display_name: "WSJ Markets"}
  - {kind: news, handle: "https://www.marketwatch.com/rss/topstories",     display_name: "MarketWatch"}
  - {kind: news, handle: "https://finance.yahoo.com/news/rssindex",        display_name: "Yahoo Finance"}
  - {kind: news, handle: "https://www.cnbc.com/id/100003114/device/rss/rss.html", display_name: "CNBC"}
  - {kind: news, handle: "https://seekingalpha.com/feed.xml",              display_name: "Seeking Alpha"}
```

- [ ] **Step 3b: Create `argus/config/sectors.yaml`**
```yaml
natural_gas:
  aliases: ["natural gas", "nat gas", "lng", "henry hub", "lng shipping", "gas carriers"]
  tickers: [NFE, DLNG]
  confidence: 0.3
agriculture:
  aliases: ["fertilizer", "fertiliser", "potash", "nitrogen", "agriculture", "crop prices", "farm"]
  tickers: [NTR]
  confidence: 0.3
ev_auto:
  aliases: ["electric vehicle", " ev ", "ev demand", "ev sales", "lucid"]
  tickers: [LCID]
  confidence: 0.3
biotech:
  aliases: ["biotech", "fda approval", "drug approval", "clinical trial", "pharma"]
  tickers: [XOMA]
  confidence: 0.3
plant_based_food:
  aliases: ["plant-based", "plant based", "alt protein", "alternative protein", "beyond meat", "meatless"]
  tickers: [BYND]
  confidence: 0.3
precious_metals:
  aliases: ["platinum", "palladium", "pgm", "precious metals"]
  tickers: [PLG]
  confidence: 0.3
```

- [ ] **Step 4: Run, verify PASS** — `... pytest -q tests/test_config.py` → `2 passed`.

- [ ] **Step 5: Commit**
```
git add argus/config/sources.yaml argus/config/sectors.yaml argus/tests/test_config.py
git commit -m "feat(argus): seed reddit+news feeds + sectors.yaml (alias->ticker map)"
```

---

### Task 3: `collect_rss` ładuje i przekazuje `sector_map`

**Files:** Modify `argus/argus/collectors/rss.py`; Modify `argus/tests/test_rss.py`

- [ ] **Step 1: Append failing test to `argus/tests/test_rss.py`**
```python
def test_collect_emits_sector_claim(session):
    from types import SimpleNamespace
    from unittest.mock import patch
    from argus.models import Asset, Source, Claim
    session.add(Asset(symbol="NFE", kind="stock", yf_symbol="NFE", scorable=True))
    src = Source(kind="news", handle="http://feed-news", display_name="WSJ Markets")
    session.add(src); session.commit()
    entry = SimpleNamespace(id="n1", title="Natural gas prices look bullish", summary="",
                            link="http://x/n1", published_parsed=(2026, 6, 4, 0, 0, 0, 0, 0, 0))
    feed = SimpleNamespace(entries=[entry])
    smap = {"natural_gas": {"aliases": ["natural gas"], "tickers": ["NFE"], "confidence": 0.3}}
    with patch("argus.collectors.rss.feedparser.parse", return_value=feed), \
         patch("argus.collectors.rss.load_sector_map", return_value=smap), \
         patch("argus.collectors.rss.get_spot_price", return_value=25.0):
        collect_rss(session, src)
    c = session.query(Claim).filter_by(asset="NFE").one()
    assert c.direction == "bull" and c.confidence == 0.3
```

- [ ] **Step 2: Run, verify FAIL** — `... pytest -q tests/test_rss.py -k sector` → fails (`load_sector_map` missing / sector_map not passed).

- [ ] **Step 3: Edit `argus/argus/collectors/rss.py`**
Add near the top imports: `import os`, `import yaml`. Add a loader function (module level):
```python
def load_sector_map(path: str = "config/sectors.yaml") -> dict:
    if os.path.exists(path):
        return yaml.safe_load(open(path, encoding="utf-8")) or {}
    return {}
```
In `collect_rss`, build the sector map once and pass it to the extractor. Change the line `for pc in extract_claims(text, assets):` to:
```python
        for pc in extract_claims(text, assets, sector_map=sector_map):
```
and just before the `for entry in feed.entries:` loop, add:
```python
    sector_map = load_sector_map()
```

- [ ] **Step 4: Run, verify PASS** — `... pytest -q tests/test_rss.py` → all green (existing 3 + new sector test = 4 passed).

- [ ] **Step 5: Commit**
```
git add argus/argus/collectors/rss.py argus/tests/test_rss.py
git commit -m "feat(argus): collect_rss loads + applies sector_map"
```

---

### Task 4: `_rss_job` łapie kind reddit/news

**Files:** Modify `argus/argus/main.py`

- [ ] **Step 1: Read `argus/argus/main.py`** — locate `_rss_job` which selects `Source.kind == "rss"`.

- [ ] **Step 2: Edit `_rss_job`** — broaden the selection to include reddit/news:
```python
def _rss_job():
    with SessionLocal() as s:
        for src in s.scalars(select(Source).where(
                Source.kind.in_(["rss", "reddit", "news"]), Source.active == True)):  # noqa: E712
            collect_rss(s, src)
```
(Only that query changes; the rest of the function stays.)

- [ ] **Step 3: Verify import + full suite in Docker**
```
docker run --rm -v "C:/Users/DAMA/Documents/docker/n8n/argus:/app" -w /app -v argus-pipcache:/root/.cache/pip -e PYTHONPATH=/app python:3.12-slim sh -c "pip install -q --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt && python -c 'import argus.main; print(\"main ok\")' && python -m pytest -q"
```
Expected: `main ok` + all tests pass.

- [ ] **Step 4: Commit**
```
git add argus/argus/main.py
git commit -m "feat(argus): rss job ingests reddit + news feeds"
```

---

### Task 5: Redeploy + smoke

**Files:** (deployment)

- [ ] **Step 1: Copy + rebuild**
```
scp -i "C:\ai\ssh-key-2026-05-19.key" -o StrictHostKeyChecking=accept-new -r "C:\Users\DAMA\Documents\docker\n8n\argus" ubuntu@84.235.174.129:~/
ssh -i "C:\ai\ssh-key-2026-05-19.key" ubuntu@84.235.174.129 "cd ~/argus && docker compose up -d --build"
```

- [ ] **Step 2: Smoke (after ~25s)** — confirm new feeds seeded + ingest produces items/claims:
```
ssh -i "C:\ai\ssh-key-2026-05-19.key" ubuntu@84.235.174.129 "sleep 25 && echo '--- health ---'; curl -sS http://localhost:8080/health; echo; cd ~/argus && docker compose exec -T app python -c \"
from argus.main import _rss_job
from argus.db import SessionLocal
from argus.models import Source, Item, Claim
from sqlalchemy import select, func
_rss_job()
s = SessionLocal()
print('sources by kind:', dict(s.execute(select(Source.kind, func.count()).group_by(Source.kind)).all()))
print('items:', s.query(Item).count(), 'claims:', s.query(Claim).count())
print('rule claims by asset:')
for a,n in s.execute(select(Claim.asset, func.count()).where(Claim.method=='rule').group_by(Claim.asset).order_by(func.count().desc()).limit(15)).all(): print('  ', a, n)
\""
```
Expected: health ok; `sources by kind` shows `reddit` (6) and `news` (5) alongside rss/hyperliquid/derived; items count jumps; some rule claims appear (possibly sector claims on stock tickers like NFE/NTR/LCID).

- [ ] **Step 3: Note for user** — verify via tunnel (8090): overview now fed by Reddit+news; source ranking will show r/… and news outlets as they accumulate outcomes.

---

## Self-Review

**Spec coverage:**
- Reddit + stock-news jako RSS (kind reddit/news), reuse collect_rss → Task 2 (feeds) + Task 4 (job) ✅
- source_type/source_name via Source.kind/display_name (bez migracji) → Task 2 (kinds) + Task 4 ✅
- rule-v2 slang (calls/puts/squeeze/bloodbath/moon/🚀...) → Task 1 ✅
- cashtagi z interpunkcją → Task 1 (tokens `[a-z0-9]+`, testy `($NFE)`, `$NFE..`) ✅
- asocjacja sektorowa (aliasy→tickery, niski conf, direct bije sektor, dedup) → Task 1 (sector_map) + Task 3 (wczytanie/przekazanie) ✅
- sectors.yaml ze strukturą aliasów, tickery ⊆ watchlista → Task 2 + test_config ✅
- watchlista akcji bez zmian, akcje scorowane przez yfinance (Increment 2) → bez zadania (istnieje) ✅
- bez nowych tabel/endpointów → potwierdzone (żaden task ich nie dodaje) ✅
- redeploy + smoke → Task 5 ✅

**Placeholder scan:** brak TODO/TBD; pełny kod w krokach. Task 5 to deployment (bez kodu).

**Type consistency:** `extract_claims(text, assets, sector_map=None)` spójne (Task 1 def ↔ Task 3 wywołanie). `load_sector_map()` (Task 3) patchowane w teście. `sector_map` shape `{key:{aliases,tickers,confidence}}` spójny: sectors.yaml (Task 2) ↔ extract_claims (Task 1) ↔ test. `PARSER_VERSION="rule-v2"` (Task 1) — claim_audit zapisze nową wersję (collect_rss bez zmian w tym zakresie). kind `reddit`/`news` (Task 2) ↔ `_rss_job` filter (Task 4).
