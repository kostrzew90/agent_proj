# Argus Dashboard v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rozszerzyć dashboard Argusa o overview ze wszystkimi aktywami (w tym akcje) + drill-down per aktywo z wykresem świecowym i markerami claimów, oraz naprawić UX selektora horyzontu.

**Architecture:** Dokładamy `charts.py` (OHLC z Binance/yfinance), trzy zmiany w `api.py` (`/api/candles`, `/api/asset/{symbol}`, poprawione `/api/assets`) i przepisujemy statyczny front (`web/index.html` + `web/app.js`) z TradingView Lightweight Charts (CDN). Bez nowych kontenerów, bez build-stepu.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, httpx, yfinance, pytest; frontend vanilla JS + Lightweight Charts (CDN). Testy w Dockerze (brak python na hoście Windows).

**Spec:** `docs/superpowers/specs/2026-06-04-argus-dashboard-v2-design.md`

---

## Konwencje (spójne we wszystkich zadaniach)

- **Brak lokalnego pythona.** Testy uruchamiać w Dockerze (przez PowerShell, by uniknąć manglowania ścieżek; flagi `--trusted-host` wymagane przez proxy SSL):
  ```
  docker run --rm -v "C:/Users/DAMA/Documents/docker/n8n/argus:/app" -w /app -v argus-pipcache:/root/.cache/pip -e PYTHONPATH=/app python:3.12-slim sh -c "pip install -q --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt && python -m pytest -q <ŚCIEŻKA>"
  ```
- OHLC format: `{"time": <epoch_sekundy:int>, "open": float, "high": float, "low": float, "close": float}`.
- `get_candles(asset, interval=None, limit=None) -> list[dict]`.
- Istniejące endpointy w `api.py` są `async def` (z wcześniejszego fixa) i `tests/test_api.py` ma helper `_client()` z `StaticPool` — **reużywaj `_client()`** w nowych testach API.
- Nowy endpoint `/api/candles` definiujemy jako zwykłe `def` (sync), żeby blokujące wywołanie HTTP szło do threadpoola i nie blokowało event-loopa. Endpointy czysto-DB pozostają `async def` (spójność).

## Struktura plików
```
argus/argus/charts.py        # NOWY — Task 1
argus/argus/api.py           # MODYFIKACJA — Tasks 2,3,4
argus/argus/web/index.html   # PRZEPISANIE — Task 5
argus/argus/web/app.js       # PRZEPISANIE — Task 5
argus/tests/test_charts.py   # NOWY — Task 1
argus/tests/test_api.py      # DOPISANIE testów — Tasks 2,3,4
```

---

### Task 1: `charts.py` — OHLC z Binance (crypto) + yfinance (stock)

**Files:**
- Create: `argus/argus/charts.py`
- Test: `argus/tests/test_charts.py`

- [ ] **Step 1: Write the failing test `argus/tests/test_charts.py`**
```python
from unittest.mock import patch, MagicMock
from argus.models import Asset
from argus.charts import get_candles

def test_crypto_candles_parsed_with_defaults():
    a = Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT")
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = [[1717200000000, "67000.0", "67500.0", "66800.0", "67200.0",
                               "10", 0, 0, 0, 0, 0, 0]]
    with patch("argus.charts.httpx.get", return_value=resp) as g:
        candles = get_candles(a)
    assert candles == [{"time": 1717200000, "open": 67000.0, "high": 67500.0,
                        "low": 66800.0, "close": 67200.0}]
    assert g.call_args.kwargs["params"]["interval"] == "1h"
    assert g.call_args.kwargs["params"]["limit"] == 168
    assert g.call_args.kwargs["params"]["symbol"] == "BTCUSDT"

def test_stock_dispatch_uses_yf_candles():
    a = Asset(symbol="LCID", kind="stock", yf_symbol="LCID")
    sentinel = [{"time": 1, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}]
    with patch("argus.charts._yf_candles", return_value=sentinel) as m:
        out = get_candles(a)
    m.assert_called_once_with("LCID", 90)
    assert out == sentinel

def test_index_kind_raises():
    a = Asset(symbol="TOTAL", kind="index")
    try:
        get_candles(a)
        assert False, "expected ValueError"
    except ValueError:
        pass
```

- [ ] **Step 2: Run, verify FAIL** — `... python -m pytest -q tests/test_charts.py` → ImportError (`argus.charts` missing).

- [ ] **Step 3: Create `argus/argus/charts.py`**
```python
import httpx
import yfinance as yf

_BINANCE = "https://api.binance.com"

def _binance_candles(symbol: str, interval: str, limit: int) -> list[dict]:
    r = httpx.get(f"{_BINANCE}/api/v3/klines",
                  params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=20)
    r.raise_for_status()
    return [{"time": int(k[0] // 1000), "open": float(k[1]), "high": float(k[2]),
             "low": float(k[3]), "close": float(k[4])} for k in r.json()]

def _yf_candles(symbol: str, limit: int) -> list[dict]:
    hist = yf.Ticker(symbol).history(period=f"{limit}d", interval="1d")
    return [{"time": int(ts.timestamp()), "open": float(row["Open"]), "high": float(row["High"]),
             "low": float(row["Low"]), "close": float(row["Close"])}
            for ts, row in hist.iterrows()]

def get_candles(asset, interval: str | None = None, limit: int | None = None) -> list[dict]:
    if asset.kind == "crypto":
        return _binance_candles(asset.binance_symbol, interval or "1h", limit or 168)
    if asset.kind == "stock":
        return _yf_candles(asset.yf_symbol, limit or 90)
    raise ValueError(f"no price source for kind: {asset.kind}")
```

- [ ] **Step 4: Run, verify PASS** — `... python -m pytest -q tests/test_charts.py` → `3 passed`.

- [ ] **Step 5: Commit**
```
git add argus/argus/charts.py argus/tests/test_charts.py
git commit -m "feat(argus): charts.get_candles (binance crypto + yfinance stock OHLC)"
```

---

### Task 2: `/api/candles` endpoint

**Files:**
- Modify: `argus/argus/api.py`
- Test: `argus/tests/test_api.py` (append)

- [ ] **Step 1: Append failing test to `argus/tests/test_api.py`** (reuse existing `_client()` helper)
```python
def test_candles_ok():
    from unittest.mock import patch
    from argus.models import Asset
    client, Sess = _client()
    s = Sess(); s.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True)); s.commit()
    fake = [{"time": 1717200000, "open": 67000.0, "high": 67500.0, "low": 66800.0, "close": 67200.0}]
    with patch("argus.api.get_candles", return_value=fake):
        r = client.get("/api/candles?asset=BTC")
    assert r.status_code == 200
    assert r.json() == fake

def test_candles_unknown_asset_404():
    client, _ = _client()
    assert client.get("/api/candles?asset=NOPE").status_code == 404

def test_candles_provider_failure_502():
    from unittest.mock import patch
    from argus.models import Asset
    client, Sess = _client()
    s = Sess(); s.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True)); s.commit()
    with patch("argus.api.get_candles", side_effect=RuntimeError("binance down")):
        r = client.get("/api/candles?asset=BTC")
    assert r.status_code == 502
```

- [ ] **Step 2: Run, verify FAIL** — `... python -m pytest -q tests/test_api.py -k candles` → fails (endpoint/import missing).

- [ ] **Step 3: Modify `argus/argus/api.py`**
At the top, extend imports:
- add `HTTPException` to the fastapi import line: `from fastapi import FastAPI, Depends, HTTPException`
- add `Asset` and `SourceAssetScore` to the models import line: `from argus.models import Asset, Source, SourceScore, SourceAssetScore, Claim, Outcome`
- add `from argus.charts import get_candles`

Add this endpoint (place it after the existing `/api/claims` route, before the static mount block):
```python
@app.get("/api/candles")
def candles(asset: str, session=Depends(get_session)):
    a = session.get(Asset, asset)
    if a is None:
        raise HTTPException(status_code=404, detail="unknown asset")
    try:
        return get_candles(a)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"candle fetch failed: {e}")
```
(Defined as sync `def` on purpose — blocking HTTP runs in threadpool.)

- [ ] **Step 4: Run, verify PASS** — `... python -m pytest -q tests/test_api.py -k candles` → `3 passed`.

- [ ] **Step 5: Commit**
```
git add argus/argus/api.py argus/tests/test_api.py
git commit -m "feat(argus): /api/candles endpoint (OHLC proxy)"
```

---

### Task 3: `/api/assets` zwraca wszystkie scorable aktywa (akcje widoczne)

**Files:**
- Modify: `argus/argus/api.py` (the existing `assets` route)
- Test: `argus/tests/test_api.py` (append)

- [ ] **Step 1: Append failing test to `argus/tests/test_api.py`**
```python
def test_assets_includes_scorable_without_claims():
    from argus.models import Asset
    client, Sess = _client()
    s = Sess()
    s.add(Asset(symbol="LCID", kind="stock", yf_symbol="LCID", scorable=True))   # no claims
    s.add(Asset(symbol="TOTAL", kind="index", scorable=False))                   # excluded
    s.commit()
    rows = client.get("/api/assets?horizon=1h").json()
    symbols = {r["asset"] for r in rows}
    assert "LCID" in symbols          # scorable asset shows even with no claims
    assert "TOTAL" not in symbols     # non-scorable excluded
    lcid = next(r for r in rows if r["asset"] == "LCID")
    assert lcid["lean"] == 0.0
    assert lcid["kind"] == "stock"
```

- [ ] **Step 2: Run, verify FAIL** — `... python -m pytest -q tests/test_api.py -k scorable` → fails (LCID missing / no `kind` field).

- [ ] **Step 3: Modify the existing `assets` route in `argus/argus/api.py`**
Replace its body so it merges `trend_lean` with the full scorable-asset list. Ensure `select` and `Asset` are imported (Asset added in Task 2). The route becomes:
```python
@app.get("/api/assets")
async def assets(horizon: str = "24h", session=Depends(get_session)):
    leans = {r["asset"]: r["lean"] for r in trend_lean(session, horizon)}
    rows = [{"asset": a.symbol, "kind": a.kind, "lean": leans.get(a.symbol, 0.0)}
            for a in session.scalars(select(Asset).where(Asset.scorable == True))]  # noqa: E712
    return sorted(rows, key=lambda r: -r["lean"])
```
(Keep `async def` to match existing style; `trend_lean` and the DB read are fast/local.)

- [ ] **Step 4: Run, verify PASS** — run `... -k "scorable or (assets and sources)"` to confirm new test passes AND the pre-existing `test_assets_and_sources_endpoints` still passes. Expect all green.

- [ ] **Step 5: Commit**
```
git add argus/argus/api.py argus/tests/test_api.py
git commit -m "feat(argus): /api/assets lists all scorable assets (stocks visible)"
```

---

### Task 4: `/api/asset/{symbol}` detail (claimy + outcome + ranking źródeł)

**Files:**
- Modify: `argus/argus/api.py`
- Test: `argus/tests/test_api.py` (append)

- [ ] **Step 1: Append failing test to `argus/tests/test_api.py`**
```python
def test_asset_detail_claims_and_sources():
    from datetime import datetime, timezone
    from argus.models import Asset, Source, Claim, Outcome, SourceAssetScore
    client, Sess = _client()
    s = Sess()
    s.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    src = Source(kind="rss", handle="h", display_name="CoinDesk"); s.add(src); s.flush()
    now = datetime.now(timezone.utc)
    c = Claim(source_id=src.id, asset="BTC", direction="bull", confidence=0.8, method="rule",
              entry_price=100.0, entry_ts=now, status="open"); s.add(c); s.flush()
    s.add(Outcome(claim_id=c.id, horizon="1h", eval_ts=now, price_at_horizon=102.0,
                  return_pct=0.02, hit=True))
    s.add(SourceAssetScore(source_id=src.id, asset="BTC", horizon="1h", n_claims=1, n_hits=1,
                           hit_rate=1.0, avg_return=0.02, decayed_score=0.7, updated_at=now))
    s.commit()
    d = client.get("/api/asset/BTC?horizon=1h").json()
    assert d["claims"][0]["source"] == "CoinDesk"
    assert d["claims"][0]["direction"] == "bull"
    assert d["claims"][0]["hit"] is True
    assert d["sources"][0]["display_name"] == "CoinDesk"
    assert d["sources"][0]["decayed_score"] == 0.7
```

- [ ] **Step 2: Run, verify FAIL** — `... python -m pytest -q tests/test_api.py -k asset_detail` → 404/fails (route missing).

- [ ] **Step 3: Add the route to `argus/argus/api.py`** (after `/api/candles`, before the static mount; `Outcome`, `SourceAssetScore`, `Source`, `Claim`, `select` already imported)
```python
@app.get("/api/asset/{symbol}")
async def asset_detail(symbol: str, horizon: str = "1h", session=Depends(get_session)):
    claim_rows = session.execute(
        select(Claim, Source.display_name)
        .join(Source, Source.id == Claim.source_id)
        .where(Claim.asset == symbol)
        .order_by(Claim.entry_ts.desc()).limit(200)
    ).all()
    outcomes = {o.claim_id: o for o in session.scalars(
        select(Outcome).where(Outcome.horizon == horizon))}
    claims = []
    for c, sname in claim_rows:
        o = outcomes.get(c.id)
        claims.append({"id": c.id, "source": sname, "direction": c.direction,
                       "confidence": c.confidence, "entry_ts": c.entry_ts.isoformat(),
                       "entry_price": c.entry_price,
                       "hit": (o.hit if o else None),
                       "return_pct": (o.return_pct if o else None)})
    src_rows = session.execute(
        select(Source.display_name, SourceAssetScore)
        .join(SourceAssetScore, SourceAssetScore.source_id == Source.id)
        .where(SourceAssetScore.asset == symbol, SourceAssetScore.horizon == horizon)
        .order_by(SourceAssetScore.decayed_score.desc())
    ).all()
    sources = [{"display_name": n, "n_claims": s.n_claims, "hit_rate": s.hit_rate,
                "decayed_score": s.decayed_score} for n, s in src_rows]
    return {"claims": claims, "sources": sources}
```

- [ ] **Step 4: Run, verify PASS** — `... python -m pytest -q tests/test_api.py -k asset_detail` → `1 passed`. Then run the WHOLE file `... python -m pytest -q tests/test_api.py` to confirm no regressions.

- [ ] **Step 5: Commit**
```
git add argus/argus/api.py argus/tests/test_api.py
git commit -m "feat(argus): /api/asset detail (claims+outcome+per-asset source scores)"
```

---

### Task 5: Frontend v2 — overview (klikalny, fix horyzontu) + drill-down ze świecami

**Files:**
- Overwrite: `argus/argus/web/index.html`
- Overwrite: `argus/argus/web/app.js`

(Brak testów automatycznych — weryfikacja manualna w Task 6 przez tunel. UI to cienka warstwa nad przetestowanym API.)

- [ ] **Step 1: Overwrite `argus/argus/web/index.html`**
```html
<!doctype html>
<html lang="pl"><head><meta charset="utf-8"><title>Argus</title>
<script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>
<style>
body{font-family:system-ui;margin:1.5rem;background:#0f1115;color:#e6e6e6}
table{border-collapse:collapse;margin-bottom:1.5rem;width:100%}
th,td{border:1px solid #2a2e37;padding:.4rem .6rem;text-align:left}
.bull{color:#3fb950}.bear{color:#f85149}
tr.asset{cursor:pointer}tr.asset:hover{background:#1c2128}
#detail{margin-top:1rem;border-top:1px solid #2a2e37;padding-top:1rem}
#chart{height:360px}
.muted{color:#8b949e}
button{background:#21262d;color:#e6e6e6;border:1px solid #2a2e37;padding:.3rem .6rem;cursor:pointer}
</style></head>
<body>
<h1>Argus — trend credibility</h1>
<label>Horyzont:
  <select id="h"><option>1h</option><option>24h</option><option>7d</option></select>
</label>
<div id="empty" class="muted"></div>
<h2>Trend-lean (aktywa)</h2><table id="assets"></table>
<h2>Ranking źródeł</h2><table id="sources"></table>
<div id="detail" style="display:none">
  <button id="closeDetail">× zamknij</button>
  <h2 id="detailTitle"></h2>
  <div id="chartErr" class="muted"></div>
  <div id="chart"></div>
  <h3>Źródła dla aktywa</h3><table id="detailSources"></table>
  <h3>Claimy</h3><table id="detailClaims"></table>
</div>
<script src="app.js"></script>
</body></html>
```

- [ ] **Step 2: Overwrite `argus/argus/web/app.js`**
```javascript
const $ = (id) => document.getElementById(id);
let chart = null, series = null;

async function getJSON(url){ const r = await fetch(url); if(!r.ok) throw new Error(r.status); return r.json(); }

async function loadOverview(){
  const h = $('h').value;
  let assets = [], sources = [];
  try { assets = await getJSON(`/api/assets?horizon=${h}`); } catch(e){}
  try { sources = await getJSON(`/api/sources?horizon=${h}`); } catch(e){}

  $('assets').innerHTML = '<tr><th>Asset</th><th>Lean</th></tr>' + assets.map(a =>
    `<tr class="asset" data-sym="${a.asset}" data-kind="${a.kind}"><td>${a.asset} <span class="muted">${a.kind}</span></td>`+
    `<td class="${a.lean>=0?'bull':'bear'}">${a.lean}</td></tr>`).join('');

  $('sources').innerHTML = '<tr><th>Źródło</th><th>n</th><th>hit%</th><th>score</th></tr>' + sources.map(s =>
    `<tr><td>${s.display_name}</td><td>${s.n_claims}</td><td>${(s.hit_rate*100).toFixed(0)}</td><td>${s.decayed_score.toFixed(2)}</td></tr>`).join('');

  // empty-state: brak rankingu źródeł = horyzont jeszcze nie dojrzał
  $('empty').textContent = sources.length === 0
    ? `Brak dojrzałych danych dla ${h} — potrzeba ~${h} od pierwszych claimów (1h dojrzewa najszybciej).`
    : '';

  document.querySelectorAll('tr.asset').forEach(tr =>
    tr.addEventListener('click', () => openDetail(tr.dataset.sym, tr.dataset.kind)));
}

async function openDetail(sym, kind){
  const h = $('h').value;
  $('detail').style.display = 'block';
  $('detailTitle').textContent = `${sym} — detal (${h})`;
  $('chartErr').textContent = '';
  // (re)create chart
  $('chart').innerHTML = '';
  chart = LightweightCharts.createChart($('chart'), {
    layout:{background:{color:'#0f1115'},textColor:'#e6e6e6'},
    grid:{vertLines:{color:'#1c2128'},horzLines:{color:'#1c2128'}},
    timeScale:{timeVisible:true}
  });
  series = chart.addCandlestickSeries();

  let candles = [];
  try { candles = await getJSON(`/api/candles?asset=${sym}`); }
  catch(e){ $('chartErr').textContent = `Nie udało się pobrać świec dla ${sym}.`; }
  series.setData(candles);

  let detail = {claims:[], sources:[]};
  try { detail = await getJSON(`/api/asset/${sym}?horizon=${h}`); } catch(e){}

  // markery z claimów (entry_ts -> epoch sekundy)
  const markers = detail.claims.map(c => {
    const t = Math.floor(new Date(c.entry_ts).getTime()/1000);
    const bull = c.direction === 'bull';
    const res = c.hit===true?' ✓':(c.hit===false?' ✗':'');
    return {time:t, position: bull?'belowBar':'aboveBar', color: bull?'#3fb950':'#f85149',
            shape: bull?'arrowUp':'arrowDown', text:`${c.source}${res}`};
  }).sort((a,b)=>a.time-b.time);
  series.setMarkers(markers);
  chart.timeScale().fitContent();

  $('detailSources').innerHTML = '<tr><th>Źródło</th><th>n</th><th>hit%</th><th>score</th></tr>' +
    detail.sources.map(s => `<tr><td>${s.display_name}</td><td>${s.n_claims}</td><td>${(s.hit_rate*100).toFixed(0)}</td><td>${s.decayed_score.toFixed(2)}</td></tr>`).join('');

  $('detailClaims').innerHTML = '<tr><th>Źródło</th><th>Dir</th><th>Conf</th><th>Kiedy</th><th>Wynik</th></tr>' +
    detail.claims.map(c => `<tr><td>${c.source}</td><td class="${c.direction==='bull'?'bull':'bear'}">${c.direction}</td><td>${c.confidence}</td><td>${c.entry_ts.slice(0,16)}</td><td>${c.hit===true?'✓':(c.hit===false?'✗':'—')}</td></tr>`).join('');
}

$('h').addEventListener('change', loadOverview);
$('closeDetail').addEventListener('click', ()=>{ $('detail').style.display='none'; });
loadOverview();
```

- [ ] **Step 3: Commit**
```
git add argus/argus/web/index.html argus/argus/web/app.js
git commit -m "feat(argus): dashboard v2 (clickable overview + horizon empty-state + candlestick drill-down)"
```

---

### Task 6: Redeploy na VPS + smoke (świece + dashboard)

**Files:** (brak — deployment)

- [ ] **Step 1: Skopiuj zaktualizowany kod na VPS**
```
scp -i "C:\ai\ssh-key-2026-05-19.key" -o StrictHostKeyChecking=accept-new -r "C:\Users\DAMA\Documents\docker\n8n\argus" ubuntu@84.235.174.129:~/
```

- [ ] **Step 2: Rebuild + restart**
```
ssh -i "C:\ai\ssh-key-2026-05-19.key" ubuntu@84.235.174.129 "cd ~/argus && docker compose up -d --build"
```

- [ ] **Step 3: Smoke (po ~20s)**
```
ssh -i "C:\ai\ssh-key-2026-05-19.key" ubuntu@84.235.174.129 "sleep 20 && echo '--- health ---' && curl -sS http://localhost:8080/health && echo && echo '--- candles BTC (first 200 chars) ---' && curl -sS 'http://localhost:8080/api/candles?asset=BTC' | head -c 200 && echo && echo '--- assets (stocks visible?) ---' && curl -sS 'http://localhost:8080/api/assets?horizon=1h' && echo && echo '--- index.html has chart lib? ---' && curl -sS http://localhost:8080/ | grep -c lightweight-charts"
```
Expected: health ok; `/api/candles?asset=BTC` zwraca tablicę OHLC (niepustą); `/api/assets` zawiera akcje (LCID/BYND/... z lean 0); `grep -c lightweight-charts` ≥ 1.

- [ ] **Step 4: Weryfikacja manualna (user przez tunel)**
Udokumentuj w raporcie instrukcję dla usera: tunel `ssh -i "C:\ai\ssh-key-2026-05-19.key" -L 8090:localhost:8080 ubuntu@84.235.174.129`, otwórz `http://localhost:8090`, horyzont na `1h`, kliknij BTC → wykres świecowy + markery claimów.

---

## Self-Review

**Spec coverage:**
- Overview wszystkie scorable aktywa + klikalne → Task 3 (`/api/assets`) + Task 5 (klik) ✅
- Selektor horyzontu default 1h + empty-state → Task 5 (`index.html` kolejność opcji, `app.js` empty-state) ✅
- Drill-down: świece + markery claimów (kolor/shape/tooltip + hit/miss) → Task 1+2 (candles) + Task 4 (claims+outcome) + Task 5 (render+markers) ✅
- Ranking źródeł per aktywo → Task 4 (`source_asset_scores`) + Task 5 ✅
- Akcje/aktywa bez claimów widoczne (lean 0) → Task 3 + test regresyjny ✅
- Świece crypto Binance / stock yfinance, dispatch po kind → Task 1 ✅
- Domyślne świec (crypto 1h/168, stock 1d/90) → Task 1 (`get_candles` defaults) ✅
- Obsługa błędów: candle fail → 502 + UI komunikat; index/macro → 400/nieklikalne → Task 2 (502/400) + Task 5 (`chartErr`, tylko scorable klikalne) ✅
- Testy backendu (candles, asset-detail, assets-regresja) → Tasks 1,2,3,4 ✅
- Redeploy + smoke → Task 6 ✅

**Placeholder scan:** brak TODO/TBD; każdy krok kodowy ma pełny kod.

**Type consistency:** OHLC `{time,open,high,low,close}` spójne (charts.py ↔ /api/candles ↔ app.js `series.setData`). `get_candles(asset, interval, limit)` spójne. Pola `/api/asset` (`claims[].source/direction/confidence/entry_ts/hit`, `sources[].display_name/n_claims/hit_rate/decayed_score`) zgodne między Task 4 a renderem w Task 5. Importy w `api.py` (HTTPException, Asset, SourceAssetScore, get_candles) dodane w Task 2 i używane w 3/4.
