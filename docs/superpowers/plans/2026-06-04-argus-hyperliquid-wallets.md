# Argus Increment 3 — Hyperliquid Wallet Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Śledzić pozycje traderów Hyperliquid jako kierunkowe claimy wpadające w pętlę wiarygodności Argusa, z agregatem „whale consensus" i UI do zarządzania portfelami (z podglądem pozycji).

**Architecture:** Nowy klient `hyperliquid.py` (clearinghouseState) + kolektor `collectors/hyperliquid.py` diffujący pozycje względem nowej tabeli `wallet_positions` i emitujący `Claim(method="position")` na otwarciu/flipie. Portfele to `Source(kind="hyperliquid")` — reużywają istniejący scorer (ranking po trafności). Consensus to osobne `Source(kind="derived")`. Endpointy `/api/wallets*` + sekcja frontu. Job w schedulerze co 15 min.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, httpx, pytest; frontend vanilla JS. Testy w Dockerze (brak python na hoście Windows).

**Spec:** `docs/superpowers/specs/2026-06-04-argus-hyperliquid-wallets-design.md`

---

## Konwencje (spójne we wszystkich zadaniach)
- **Brak lokalnego pythona.** Testy w Dockerze (PowerShell; flagi trusted-host przez proxy SSL):
  ```
  docker run --rm -v "C:/Users/DAMA/Documents/docker/n8n/argus:/app" -w /app -v argus-pipcache:/root/.cache/pip -e PYTHONPATH=/app python:3.12-slim sh -c "pip install -q --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt && python -m pytest -q <ŚCIEŻKA>"
  ```
- Position dict: `{"coin":str, "side":"long"|"short", "szi":float, "entry_px":float, "position_value":float}`. `fetch_positions(address) -> {"equity":float, "positions":[<position dict>]}`.
- Kierunek: long→`"bull"`, short→`"bear"`. Metoda claima: `"position"`. parser_version: `"hyperliquid-v1"`.
- Istniejące endpointy `api.py` są `async def`; `tests/test_api.py` ma helper `_client()` (StaticPool). Endpointy z blokującym HTTP (`/api/wallets/preview`) definiujemy jako sync `def`.

## Struktura plików
```
argus/argus/hyperliquid.py            # NOWY — Task 4 (klient HL)
argus/argus/collectors/hyperliquid.py # NOWY — Task 5 (kolektor diff→claim) + Task 8 (consensus)
argus/argus/models.py                 # MOD — Task 3 (WalletPosition)
argus/argus/evaluator.py              # MOD — Task 2 (30d horizon)
argus/argus/api.py                    # MOD — Task 6 (endpointy wallets)
argus/argus/main.py                   # MOD — Task 9 (job + seed)
argus/argus/web/index.html, app.js    # MOD — Task 7 (sekcja portfeli)
argus/config/wallets.yaml             # NOWY — Task 1 (bootstrap adresów + consensus source)
argus/tests/test_evaluator.py         # MOD — Task 2
argus/tests/test_models.py            # MOD — Task 3
argus/tests/test_hyperliquid.py       # NOWY — Task 4
argus/tests/test_collector_hl.py      # NOWY — Tasks 5, 8
argus/tests/test_api.py               # MOD — Task 6
```

---

### Task 1: Spike — potwierdź kształt pozycji + bootstrap adresów

**Files:** Create `argus/docs/hyperliquid-findings.md`, `argus/config/wallets.yaml`

Investigation (bez TDD). Wykonuje agent z dostępem do sieci (najlepiej na VPS — laptop blokuje SSL proxy).

- [ ] **Step 1: Potwierdź żywy kształt pozycji** — znajdź adres z OTWARTYMI pozycjami (np. z hypurrscan.io „top positions"/„leaderboard") i:
```
curl -sS -X POST https://api.hyperliquid.xyz/info -H "Content-Type: application/json" -d "{\"type\":\"clearinghouseState\",\"user\":\"0x<ADDR>\"}" | python -m json.tool | head -60
```
Zapisz w `hyperliquid-findings.md`: dokładne pola `assetPositions[].position` (`coin`, `szi`, `entryPx`, `positionValue`, `leverage`) + `marginSummary.accountValue`. Jeśli realne pola różnią się od założeń (`coin/szi/entryPx/positionValue`) — zanotuj i ZGŁOŚ (wpływa na Task 4 parser).

- [ ] **Step 2: Zbierz pulę adresów** — z publicznego trackera HL (hypurrscan.io leaderboard / top traders) wypisz 5–10 adresów po PnL/ROI. Jeśli żaden tracker nie da się odczytać — zapisz 2–3 adresy, które dały niepustą `clearinghouseState` w Step 1.

- [ ] **Step 3: Zapisz `argus/config/wallets.yaml`** (format zgodny z `seed_sources`; consensus jako derived):
```yaml
sources:
  - {kind: hyperliquid, handle: "0xADDR1", display_name: "whale-1"}
  - {kind: hyperliquid, handle: "0xADDR2", display_name: "whale-2"}
  # ... (adresy ze Step 2)
  - {kind: derived, handle: "whale-consensus", display_name: "Whale Consensus"}
```

- [ ] **Step 4: Commit**
```
git add argus/docs/hyperliquid-findings.md argus/config/wallets.yaml
git commit -m "chore(argus): HL spike findings + wallets bootstrap seed"
```

---

### Task 2: 30d horizon (system-wide, addytywnie)

**Files:** Modify `argus/argus/evaluator.py`; Modify `argus/tests/test_evaluator.py`

- [ ] **Step 1: Zaktualizuj `tests/test_evaluator.py`** — zmień w helperze `_setup` wiek claima na 31 dni (żeby 30d też był „due"), aby asercja `set(outs)==set(HORIZONS)` obejmowała 30d. Zmień JEDNĄ linię w `_setup`:
```python
    old = datetime.now(timezone.utc) - timedelta(days=31)  # po wszystkich horyzontach (w tym 30d)
```
(Reszta testu bez zmian — `set(outs)==set(HORIZONS)` teraz wymaga 30d.)

- [ ] **Step 2: Run, verify FAIL** — `... pytest -q tests/test_evaluator.py` → `test_bull_hit_when_price_up` faila (outs nie zawiera 30d, bo HORIZONS go nie ma).

- [ ] **Step 3: Edytuj `argus/argus/evaluator.py`** — dodaj 30d do obu słowników:
```python
HORIZONS = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}
THRESHOLDS = {"1h": 0.005, "24h": 0.015, "7d": 0.04, "30d": 0.08}
```

- [ ] **Step 4: Run, verify PASS** — `... pytest -q tests/test_evaluator.py` → wszystkie zielone (outs = {1h,24h,7d,30d}).

- [ ] **Step 5: Commit**
```
git add argus/argus/evaluator.py argus/tests/test_evaluator.py
git commit -m "feat(argus): add 30d horizon (system-wide)"
```

---

### Task 3: `WalletPosition` model

**Files:** Modify `argus/argus/models.py`; Modify `argus/tests/test_models.py`

- [ ] **Step 1: Dopisz failing test do `tests/test_models.py`**
```python
def test_wallet_position_roundtrip(session):
    from datetime import datetime, timezone
    from argus.models import Source, WalletPosition
    s = Source(kind="hyperliquid", handle="0xabc", display_name="w1"); session.add(s); session.flush()
    now = datetime.now(timezone.utc)
    session.add(WalletPosition(source_id=s.id, coin="BTC", side="long", szi=0.5,
                               entry_px=67000.0, position_value=33500.0,
                               opened_ts=now, last_seen_ts=now, open=True))
    session.commit()
    wp = session.query(WalletPosition).one()
    assert wp.coin == "BTC" and wp.side == "long" and wp.open is True
```

- [ ] **Step 2: Run, verify FAIL** — `... pytest -q tests/test_models.py -k wallet_position` → ImportError (WalletPosition missing).

- [ ] **Step 3: Dodaj do `argus/argus/models.py`** (na końcu pliku):
```python
class WalletPosition(Base):
    __tablename__ = "wallet_positions"
    __table_args__ = (UniqueConstraint("source_id", "coin"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    coin: Mapped[str] = mapped_column(String)
    side: Mapped[str] = mapped_column(String)              # long|short
    szi: Mapped[float] = mapped_column(Float)
    entry_px: Mapped[float] = mapped_column(Float)
    position_value: Mapped[float] = mapped_column(Float)
    opened_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    open: Mapped[bool] = mapped_column(Boolean)
```

- [ ] **Step 4: Run, verify PASS** — `... pytest -q tests/test_models.py` → wszystkie zielone.

- [ ] **Step 5: Commit**
```
git add argus/argus/models.py argus/tests/test_models.py
git commit -m "feat(argus): WalletPosition model (HL position state)"
```

---

### Task 4: `hyperliquid.py` — klient clearinghouseState

**Files:** Create `argus/argus/hyperliquid.py`; Test `argus/tests/test_hyperliquid.py`

> Jeśli Task 1 wykazał inne nazwy pól w `assetPositions[].position`, dostosuj parser w Step 3 i wartości w teście.

- [ ] **Step 1: Write failing test `argus/tests/test_hyperliquid.py`**
```python
from unittest.mock import patch, MagicMock
from argus.hyperliquid import fetch_positions

def _resp(payload):
    r = MagicMock(); r.raise_for_status.return_value = None; r.json.return_value = payload; return r

def test_parses_long_and_short_and_skips_zero():
    payload = {
        "marginSummary": {"accountValue": "10000.0"},
        "assetPositions": [
            {"position": {"coin": "BTC", "szi": "0.5", "entryPx": "66000.0", "positionValue": "33500.0"}},
            {"position": {"coin": "ETH", "szi": "-2.0", "entryPx": "1900.0", "positionValue": "3800.0"}},
            {"position": {"coin": "SOL", "szi": "0.0", "entryPx": "150.0", "positionValue": "0.0"}},
        ],
    }
    with patch("argus.hyperliquid.httpx.post", return_value=_resp(payload)) as p:
        out = fetch_positions("0xabc")
    assert out["equity"] == 10000.0
    coins = {x["coin"]: x for x in out["positions"]}
    assert set(coins) == {"BTC", "ETH"}       # SOL szi=0 skipped
    assert coins["BTC"]["side"] == "long" and coins["BTC"]["position_value"] == 33500.0
    assert coins["ETH"]["side"] == "short"
    assert p.call_args.kwargs["json"] == {"type": "clearinghouseState", "user": "0xabc"}
```

- [ ] **Step 2: Run, verify FAIL** — ImportError.

- [ ] **Step 3: Create `argus/argus/hyperliquid.py`**
```python
import httpx

_HL = "https://api.hyperliquid.xyz/info"

def fetch_positions(address: str) -> dict:
    r = httpx.post(_HL, json={"type": "clearinghouseState", "user": address}, timeout=20)
    r.raise_for_status()
    data = r.json()
    equity = float(data.get("marginSummary", {}).get("accountValue", 0) or 0)
    positions = []
    for ap in data.get("assetPositions", []):
        p = ap.get("position", {})
        szi = float(p.get("szi", 0) or 0)
        if szi == 0:
            continue
        positions.append({"coin": p["coin"], "side": "long" if szi > 0 else "short",
                          "szi": szi, "entry_px": float(p.get("entryPx") or 0),
                          "position_value": float(p.get("positionValue") or 0)})
    return {"equity": equity, "positions": positions}
```

- [ ] **Step 4: Run, verify PASS** — `1 passed`.

- [ ] **Step 5: Commit**
```
git add argus/argus/hyperliquid.py argus/tests/test_hyperliquid.py
git commit -m "feat(argus): hyperliquid client (clearinghouseState parser)"
```

---

### Task 5: `collectors/hyperliquid.py` — diff → claims + wallet_positions

**Files:** Create `argus/argus/collectors/hyperliquid.py`; Test `argus/tests/test_collector_hl.py`

- [ ] **Step 1: Write failing test `argus/tests/test_collector_hl.py`**
```python
from unittest.mock import patch
from argus.models import Asset, Source, Claim, ClaimAudit, WalletPosition
from argus.collectors.hyperliquid import collect_wallet

def _seed(session):
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT", scorable=True))
    s = Source(kind="hyperliquid", handle="0xabc", display_name="w1"); session.add(s); session.commit()
    return s

def _data(positions, equity=10000.0):
    return {"equity": equity, "positions": positions}

def test_new_watchlist_long_creates_bull_claim(session):
    s = _seed(session)
    pos = [{"coin": "BTC", "side": "long", "szi": 0.1, "entry_px": 66000.0, "position_value": 8000.0}]
    with patch("argus.collectors.hyperliquid.fetch_positions", return_value=_data(pos)), \
         patch("argus.collectors.hyperliquid.get_spot_price", return_value=67000.0):
        n = collect_wallet(session, s)
    assert n == 1
    c = session.query(Claim).one()
    assert c.asset == "BTC" and c.direction == "bull" and c.method == "position"
    assert c.entry_price == 67000.0
    assert abs(c.confidence - 0.8) < 1e-9          # 8000/10000
    assert session.query(WalletPosition).filter_by(coin="BTC", open=True).count() == 1
    assert session.query(ClaimAudit).one().parser_version == "hyperliquid-v1"

def test_no_change_no_new_claim(session):
    s = _seed(session)
    pos = [{"coin": "BTC", "side": "long", "szi": 0.1, "entry_px": 66000.0, "position_value": 8000.0}]
    with patch("argus.collectors.hyperliquid.fetch_positions", return_value=_data(pos)), \
         patch("argus.collectors.hyperliquid.get_spot_price", return_value=67000.0):
        collect_wallet(session, s)
        collect_wallet(session, s)
    assert session.query(Claim).count() == 1

def test_flip_creates_new_claim(session):
    s = _seed(session)
    with patch("argus.collectors.hyperliquid.get_spot_price", return_value=67000.0):
        with patch("argus.collectors.hyperliquid.fetch_positions",
                   return_value=_data([{"coin":"BTC","side":"long","szi":0.1,"entry_px":66000.0,"position_value":8000.0}])):
            collect_wallet(session, s)
        with patch("argus.collectors.hyperliquid.fetch_positions",
                   return_value=_data([{"coin":"BTC","side":"short","szi":-0.1,"entry_px":67000.0,"position_value":8000.0}])):
            collect_wallet(session, s)
    dirs = sorted(c.direction for c in session.query(Claim).all())
    assert dirs == ["bear", "bull"]
    assert session.query(WalletPosition).filter_by(coin="BTC").one().side == "short"

def test_off_watchlist_records_position_no_claim(session):
    s = _seed(session)
    pos = [{"coin": "HYPE", "side": "long", "szi": 100.0, "entry_px": 20.0, "position_value": 2000.0}]
    with patch("argus.collectors.hyperliquid.fetch_positions", return_value=_data(pos)), \
         patch("argus.collectors.hyperliquid.get_spot_price", return_value=67000.0):
        collect_wallet(session, s)
    assert session.query(Claim).count() == 0
    assert session.query(WalletPosition).filter_by(coin="HYPE", open=True).count() == 1

def test_confidence_fallback_when_no_equity(session):
    s = _seed(session)
    pos = [{"coin": "BTC", "side": "long", "szi": 0.1, "entry_px": 66000.0, "position_value": 8000.0}]
    with patch("argus.collectors.hyperliquid.fetch_positions", return_value=_data(pos, equity=0.0)), \
         patch("argus.collectors.hyperliquid.get_spot_price", return_value=67000.0):
        collect_wallet(session, s)
    assert abs(session.query(Claim).one().confidence - 0.7) < 1e-9
```

- [ ] **Step 2: Run, verify FAIL** — ImportError.

- [ ] **Step 3: Create `argus/argus/collectors/hyperliquid.py`**
```python
import logging
from datetime import datetime, timezone
from sqlalchemy import select
from argus.models import Asset, Claim, ClaimAudit, WalletPosition
from argus.hyperliquid import fetch_positions
from argus.prices import get_spot_price

logger = logging.getLogger(__name__)

def _confidence(position_value: float, equity: float) -> float:
    if equity and equity > 0:
        return round(max(0.5, min(0.9, position_value / equity)), 2)
    return 0.7

def collect_wallet(session, source) -> int:
    data = fetch_positions(source.handle)
    equity = data["equity"]
    scorable = {a.symbol: a for a in session.scalars(select(Asset).where(Asset.scorable == True))}  # noqa: E712
    now = datetime.now(timezone.utc)
    seen = set()
    created = 0
    for pos in data["positions"]:
        coin, side = pos["coin"], pos["side"]
        seen.add(coin)
        wp = session.scalar(select(WalletPosition).where(
            WalletPosition.source_id == source.id, WalletPosition.coin == coin))
        is_new = wp is None or not wp.open
        is_flip = wp is not None and wp.open and wp.side != side
        if (is_new or is_flip) and coin in scorable:
            try:
                spot = get_spot_price(scorable[coin])
            except Exception as e:
                logger.warning("skip wallet claim %s %s: price failed: %s", source.handle, coin, e)
                spot = None
            if spot is not None:
                direction = "bull" if side == "long" else "bear"
                claim = Claim(source_id=source.id, asset=coin, direction=direction,
                              confidence=_confidence(pos["position_value"], equity), method="position",
                              entry_price=spot, entry_ts=now, status="open")
                session.add(claim); session.flush()
                session.add(ClaimAudit(claim_id=claim.id,
                    raw_text=f"{source.display_name} {side} {coin}",
                    parsed_claim={"direction": direction, "coin": coin,
                                  "wallet_entry_px": pos["entry_px"], "detected_px": spot,
                                  "position_value": pos["position_value"], "equity": equity},
                    parser_version="hyperliquid-v1"))
                created += 1
        if wp is None:
            session.add(WalletPosition(source_id=source.id, coin=coin, side=side, szi=pos["szi"],
                                       entry_px=pos["entry_px"], position_value=pos["position_value"],
                                       opened_ts=now, last_seen_ts=now, open=True))
        else:
            if not wp.open or wp.side != side:
                wp.opened_ts = now
            wp.side = side; wp.szi = pos["szi"]; wp.entry_px = pos["entry_px"]
            wp.position_value = pos["position_value"]; wp.last_seen_ts = now; wp.open = True
    for wp in session.scalars(select(WalletPosition).where(
            WalletPosition.source_id == source.id, WalletPosition.open == True)):  # noqa: E712
        if wp.coin not in seen:
            wp.open = False; wp.last_seen_ts = now
    session.commit()
    return created
```

- [ ] **Step 4: Run, verify PASS** — `... pytest -q tests/test_collector_hl.py` → `5 passed`.

- [ ] **Step 5: Commit**
```
git add argus/argus/collectors/hyperliquid.py argus/tests/test_collector_hl.py
git commit -m "feat(argus): HL wallet collector (diff -> position claims + wallet_positions)"
```

---

### Task 6: Endpointy `/api/wallets*`

**Files:** Modify `argus/argus/api.py`; Test `argus/tests/test_api.py` (append)

- [ ] **Step 1: Append failing tests to `tests/test_api.py`**
```python
def test_wallet_preview_validates_and_lists():
    from unittest.mock import patch
    client, _ = _client()
    assert client.get("/api/wallets/preview?address=bad").status_code == 422
    fake = {"equity": 10000.0, "positions": [{"coin": "BTC", "side": "long", "position_value": 8000.0}]}
    with patch("argus.api.fetch_positions", return_value=fake):
        r = client.get("/api/wallets/preview?address=0x" + "a"*40)
    assert r.status_code == 200
    assert r.json()["positions"][0]["coin"] == "BTC"

def test_wallet_add_and_list_and_deactivate():
    from datetime import datetime, timezone
    from argus.models import Source, SourceScore
    client, Sess = _client()
    addr = "0x" + "b"*40
    assert client.post("/api/wallets", json={"address": "nope"}).status_code == 422
    r = client.post("/api/wallets", json={"address": addr, "label": "whale-x"})
    assert r.status_code == 200
    # idempotent
    client.post("/api/wallets", json={"address": addr, "label": "whale-x"})
    s = Sess()
    src = s.query(Source).filter_by(handle=addr).one()
    s.add(SourceScore(source_id=src.id, horizon="24h", n_claims=3, hit_rate=0.66,
                      avg_return=0.01, decayed_score=0.6, updated_at=datetime.now(timezone.utc)))
    s.commit()
    rows = client.get("/api/wallets").json()
    row = next(r for r in rows if r["handle"] == addr)
    assert row["acc_24h"] == 0.66 and row["display_name"] == "whale-x"
    assert client.post(f"/api/wallets/{src.id}/deactivate").status_code == 200
    assert s.get(Source, src.id).active is False
```

- [ ] **Step 2: Run, verify FAIL** — `... pytest -q tests/test_api.py -k wallet` → fails (routes missing).

- [ ] **Step 3: Edit `argus/argus/api.py`**
Add imports near the top: `import re`, `from sqlalchemy import select, func` (extend the existing sqlalchemy import to include `func`), add `WalletPosition` to the models import line, and `from argus.hyperliquid import fetch_positions`. Then add (after `/api/asset/{symbol}`, before the static mount):
```python
_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")

@app.get("/api/wallets")
async def wallets(session=Depends(get_session)):
    out = []
    for src in session.scalars(select(Source).where(Source.kind == "hyperliquid")):
        scores = {sc.horizon: sc.hit_rate for sc in session.scalars(
            select(SourceScore).where(SourceScore.source_id == src.id))}
        active = session.scalar(select(func.count()).select_from(WalletPosition).where(
            WalletPosition.source_id == src.id, WalletPosition.open == True)) or 0  # noqa: E712
        out.append({"id": src.id, "display_name": src.display_name, "handle": src.handle,
                    "active": src.active, "acc_24h": scores.get("24h"),
                    "acc_7d": scores.get("7d"), "acc_30d": scores.get("30d"),
                    "active_positions": active})
    return out

@app.get("/api/wallets/preview")
def wallet_preview(address: str):
    if not _ADDR.match(address):
        raise HTTPException(status_code=422, detail="invalid address format")
    try:
        data = fetch_positions(address)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"cannot fetch positions: {e}")
    return {"address": address, "equity": data["equity"],
            "positions": [{"coin": p["coin"], "side": p["side"], "position_value": p["position_value"]}
                          for p in data["positions"]]}

@app.post("/api/wallets")
async def add_wallet(payload: dict, session=Depends(get_session)):
    address = (payload.get("address") or "").strip()
    if not _ADDR.match(address):
        raise HTTPException(status_code=422, detail="invalid address format")
    label = (payload.get("label") or address[:10]).strip()
    if session.scalar(select(Source).where(Source.handle == address)) is None:
        session.add(Source(kind="hyperliquid", handle=address, display_name=label, active=True))
        session.commit()
    return {"status": "ok", "address": address}

@app.post("/api/wallets/{wallet_id}/deactivate")
async def deactivate_wallet(wallet_id: int, session=Depends(get_session)):
    src = session.get(Source, wallet_id)
    if src is None:
        raise HTTPException(status_code=404, detail="unknown wallet")
    src.active = False
    session.commit()
    return {"status": "ok"}
```

- [ ] **Step 4: Run, verify PASS** — `... pytest -q tests/test_api.py -k wallet` (2 passed) then WHOLE file `... pytest -q tests/test_api.py` (no regressions).

- [ ] **Step 5: Commit**
```
git add argus/argus/api.py argus/tests/test_api.py
git commit -m "feat(argus): /api/wallets endpoints (list/preview/add/deactivate)"
```

---

### Task 7: Frontend — sekcja „Śledzone portfele" (lista + add z preview)

**Files:** Modify `argus/argus/web/index.html`; Modify `argus/argus/web/app.js` (verify manualnie w Task 9)

- [ ] **Step 1: Read `argus/argus/web/index.html` and `app.js`** to append, not clobber existing v2.

- [ ] **Step 2: Add to `index.html`** before `<div id="detail"...>`:
```html
<h2>Śledzone portfele (Hyperliquid)</h2>
<table id="wallets"></table>
<div>
  <input id="wAddr" placeholder="0x... adres" size="46">
  <input id="wLabel" placeholder="etykieta">
  <button id="wPreview">Podgląd pozycji</button>
  <button id="wSave" style="display:none">Zapisz</button>
  <div id="wPreviewOut" class="muted"></div>
</div>
```

- [ ] **Step 3: Append to `app.js`** (and call `loadWallets()` inside `loadOverview()` after sources render, plus the listeners at the bottom):
```javascript
async function loadWallets(){
  let rows = [];
  try { rows = await getJSON('/api/wallets'); } catch(e){}
  const pct = v => v==null ? '—' : (v*100).toFixed(0)+'%';
  $('wallets').innerHTML = '<tr><th>Portfel</th><th>Acc 24h</th><th>Acc 7d</th><th>Acc 30d</th><th>Pozycje</th><th></th></tr>' +
    rows.map(w => `<tr><td title="${w.handle}">${w.display_name}${w.active?'':' (off)'}</td>`+
      `<td>${pct(w.acc_24h)}</td><td>${pct(w.acc_7d)}</td><td>${pct(w.acc_30d)}</td>`+
      `<td>${w.active_positions}</td>`+
      `<td><button data-wid="${w.id}" class="deact">deactivate</button></td></tr>`).join('');
  document.querySelectorAll('button.deact').forEach(b => b.addEventListener('click', async () => {
    await fetch(`/api/wallets/${b.dataset.wid}/deactivate`, {method:'POST'}); loadWallets();
  }));
}

async function previewWallet(){
  const addr = $('wAddr').value.trim();
  $('wPreviewOut').textContent = 'Ładowanie...';
  try {
    const d = await getJSON(`/api/wallets/preview?address=${addr}`);
    $('wPreviewOut').innerHTML = `equity $${d.equity.toFixed(0)} — ` +
      d.positions.map(p => `${p.side==='long'?'LONG':'SHORT'} ${p.coin}`).join(', ') || 'brak pozycji';
    $('wSave').style.display = 'inline';
  } catch(e){ $('wPreviewOut').textContent = 'Błędny adres lub brak danych.'; $('wSave').style.display='none'; }
}

async function saveWallet(){
  const addr = $('wAddr').value.trim(), label = $('wLabel').value.trim();
  const r = await fetch('/api/wallets', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({address:addr, label})});
  if(r.ok){ $('wAddr').value=''; $('wLabel').value=''; $('wPreviewOut').textContent='Dodano.';
    $('wSave').style.display='none'; loadWallets(); }
  else { $('wPreviewOut').textContent = 'Nie zapisano (zły adres?).'; }
}
```
W `loadOverview()` dodaj wywołanie `loadWallets();` (na końcu funkcji). Na dole pliku dodaj:
```javascript
$('wPreview').addEventListener('click', previewWallet);
$('wSave').addEventListener('click', saveWallet);
```

- [ ] **Step 4: Commit**
```
git add argus/argus/web/index.html argus/argus/web/app.js
git commit -m "feat(argus): dashboard — tracked wallets section (list + add with preview)"
```

---

### Task 8: Whale Consensus (cuttable)

**Files:** Modify `argus/argus/collectors/hyperliquid.py`; Test `argus/tests/test_collector_hl.py` (append)

- [ ] **Step 1: Append failing test to `tests/test_collector_hl.py`**
```python
def test_consensus_emits_claim_when_supermajority(session):
    from datetime import datetime, timezone
    from argus.models import Asset, Source, Claim, WalletPosition
    from argus.collectors.hyperliquid import compute_consensus
    session.add(Asset(symbol="SOL", kind="crypto", binance_symbol="SOLUSDT", scorable=True))
    cons = Source(kind="derived", handle="whale-consensus", display_name="Whale Consensus")
    session.add(cons)
    now = datetime.now(timezone.utc)
    for i in range(6):
        w = Source(kind="hyperliquid", handle=f"0x{i:040x}", display_name=f"w{i}")
        session.add(w); session.flush()
        side = "long" if i < 5 else "short"          # 5/6 long
        session.add(WalletPosition(source_id=w.id, coin="SOL", side=side, szi=1.0, entry_px=150.0,
                                   position_value=1000.0, opened_ts=now, last_seen_ts=now, open=True))
    session.commit()
    with patch("argus.collectors.hyperliquid.get_spot_price", return_value=150.0):
        n = compute_consensus(session, min_wallets=4, ratio=0.66)
    assert n == 1
    c = session.query(Claim).filter_by(source_id=cons.id).one()
    assert c.asset == "SOL" and c.direction == "bull"
    # second run, no change -> no new claim
    with patch("argus.collectors.hyperliquid.get_spot_price", return_value=150.0):
        assert compute_consensus(session, min_wallets=4, ratio=0.66) == 0

def test_consensus_below_threshold_no_claim(session):
    from datetime import datetime, timezone
    from argus.models import Asset, Source, WalletPosition
    from argus.collectors.hyperliquid import compute_consensus
    session.add(Asset(symbol="SOL", kind="crypto", binance_symbol="SOLUSDT", scorable=True))
    session.add(Source(kind="derived", handle="whale-consensus", display_name="Whale Consensus"))
    now = datetime.now(timezone.utc)
    for i in range(2):                                # tylko 2 portfele < min_wallets
        w = Source(kind="hyperliquid", handle=f"0x{i:040x}", display_name=f"w{i}"); session.add(w); session.flush()
        session.add(WalletPosition(source_id=w.id, coin="SOL", side="long", szi=1.0, entry_px=150.0,
                                   position_value=1000.0, opened_ts=now, last_seen_ts=now, open=True))
    session.commit()
    with patch("argus.collectors.hyperliquid.get_spot_price", return_value=150.0):
        assert compute_consensus(session, min_wallets=4, ratio=0.66) == 0
```

- [ ] **Step 2: Run, verify FAIL** — ImportError (`compute_consensus` missing).

- [ ] **Step 3: Append to `argus/argus/collectors/hyperliquid.py`** (reuse `WalletPosition` rows of the consensus source as its own state to dedup):
```python
def compute_consensus(session, min_wallets: int = 4, ratio: float = 0.66) -> int:
    from argus.models import Source
    cons = session.scalar(select(Source).where(Source.kind == "derived",
                                               Source.handle == "whale-consensus"))
    if cons is None:
        return 0
    scorable = {a.symbol for a in session.scalars(select(Asset).where(Asset.scorable == True))}  # noqa: E712
    hl_ids = [s.id for s in session.scalars(select(Source).where(
        Source.kind == "hyperliquid", Source.active == True))]  # noqa: E712
    now = datetime.now(timezone.utc)
    # tally open positions per coin across HL wallets
    tally = {}  # coin -> [long, short]
    for wp in session.scalars(select(WalletPosition).where(
            WalletPosition.open == True, WalletPosition.source_id.in_(hl_ids or [-1]))):  # noqa: E712
        if wp.coin not in scorable:
            continue
        t = tally.setdefault(wp.coin, [0, 0])
        t[0 if wp.side == "long" else 1] += 1
    created = 0
    for coin, (longs, shorts) in tally.items():
        total = longs + shorts
        if total < min_wallets:
            continue
        side = "long" if longs / total >= ratio else ("short" if shorts / total >= ratio else None)
        if side is None:
            continue
        state = session.scalar(select(WalletPosition).where(
            WalletPosition.source_id == cons.id, WalletPosition.coin == coin))
        if state is not None and state.open and state.side == side:
            continue  # no change
        try:
            spot = get_spot_price(next(a for a in session.scalars(
                select(Asset).where(Asset.symbol == coin))))
        except Exception as e:
            logger.warning("consensus skip %s: price failed: %s", coin, e)
            continue
        direction = "bull" if side == "long" else "bear"
        claim = Claim(source_id=cons.id, asset=coin, direction=direction,
                      confidence=round(max(longs, shorts) / total, 2), method="position",
                      entry_price=spot, entry_ts=now, status="open")
        session.add(claim); session.flush()
        session.add(ClaimAudit(claim_id=claim.id, raw_text=f"consensus {side} {coin} {longs}L/{shorts}S",
                    parsed_claim={"direction": direction, "coin": coin, "longs": longs, "shorts": shorts},
                    parser_version="consensus-v1"))
        if state is None:
            session.add(WalletPosition(source_id=cons.id, coin=coin, side=side, szi=0.0, entry_px=spot,
                                       position_value=0.0, opened_ts=now, last_seen_ts=now, open=True))
        else:
            state.side = side; state.open = True; state.last_seen_ts = now; state.opened_ts = now
        created += 1
    session.commit()
    return created
```

- [ ] **Step 4: Run, verify PASS** — `... pytest -q tests/test_collector_hl.py` → all green (5 + 2 = 7 passed).

- [ ] **Step 5: Commit**
```
git add argus/argus/collectors/hyperliquid.py argus/tests/test_collector_hl.py
git commit -m "feat(argus): whale-consensus aggregate claims"
```

---

### Task 9: Scheduler wiring + seed + redeploy + smoke

**Files:** Modify `argus/argus/main.py`; deployment

- [ ] **Step 1: Edit `argus/argus/main.py`** — add wallets seed + HL job. After the existing `seed_sources(...)` call in `bootstrap()`, add a seed of `config/wallets.yaml` (reuse `seed_sources`; guard if file missing). Add imports and job:
```python
import os
from argus.collectors.hyperliquid import collect_wallet, compute_consensus

def _hyperliquid_job():
    from argus.models import Source
    with SessionLocal() as s:
        for src in s.scalars(select(Source).where(Source.kind == "hyperliquid", Source.active == True)):  # noqa: E712
            try:
                collect_wallet(s, src)
            except Exception as e:
                import logging; logging.getLogger(__name__).warning("HL collect failed %s: %s", src.handle, e)
        compute_consensus(s)
```
In `bootstrap()`:
```python
        seed_sources(s, settings.sources_path)
        if os.path.exists("config/wallets.yaml"):
            seed_sources(s, "config/wallets.yaml")
```
And register the job near the other `add_interval` calls:
```python
    sched.add_interval("hyperliquid", _hyperliquid_job, minutes=15)
```

- [ ] **Step 2: Commit**
```
git add argus/argus/main.py
git commit -m "feat(argus): wire hyperliquid collector + consensus into scheduler + seed wallets"
```

- [ ] **Step 3: Redeploy to VPS**
```
scp -i "C:\ai\ssh-key-2026-05-19.key" -o StrictHostKeyChecking=accept-new -r "C:\Users\DAMA\Documents\docker\n8n\argus" ubuntu@84.235.174.129:~/
ssh -i "C:\ai\ssh-key-2026-05-19.key" ubuntu@84.235.174.129 "cd ~/argus && docker compose up -d --build"
```

- [ ] **Step 4: Smoke (after ~25s)**
```
ssh -i "C:\ai\ssh-key-2026-05-19.key" ubuntu@84.235.174.129 "sleep 25 && echo '--- health ---'; curl -sS http://localhost:8080/health; echo; echo '--- wallets ---'; curl -sS http://localhost:8080/api/wallets; echo; echo '--- trigger HL once ---'; cd ~/argus && docker compose exec -T app python -c \"from argus.main import _hyperliquid_job; _hyperliquid_job(); from argus.db import SessionLocal; from argus.models import Claim, WalletPosition; s=SessionLocal(); print('position-claims:', s.query(Claim).filter_by(method='position').count(), 'wallet_positions:', s.query(WalletPosition).count())\""
```
Expected: health ok; `/api/wallets` zwraca listę seedowanych portfeli (acc pola null na starcie); po triggerze widać `wallet_positions` > 0 (jeśli seedowane adresy mają otwarte pozycje) i ewentualnie position-claims dla coinów z watchlisty.

- [ ] **Step 5: Instrukcja weryfikacji (user, tunel)** — udokumentuj: tunel na 8090, otwórz dashboard, sekcja „Śledzone portfele", wklej adres → „Podgląd pozycji" → „Zapisz".

---

## Self-Review

**Spec coverage:**
- Źródło=portfel (`kind=hyperliquid`) + consensus (`kind=derived`) → Tasks 1,6,8,9 ✅
- `wallet_positions` (stan + off-watchlist) → Task 3, używane w 5/8 ✅
- Klient clearinghouseState + parser → Task 4 ✅
- Collector diff→claim (open/flip), wszystkie pozycje do wallet_positions, off-watchlist bez claima → Task 5 ✅
- entry_price=spot + metadata (wallet_entry_px, detected_px) w claim_audit → Task 5 ✅
- confidence = position_value/equity clamp [0.5,0.9], fallback 0.7 → Task 5 ✅
- ranking po directional accuracy (istniejący scorer) → bez zmian, prezentowane w `/api/wallets` acc_* → Task 6 ✅
- 30d horizon system-wide → Task 2 ✅
- consensus ≥min_wallets & ≥ratio, dedup, własny scored claim → Task 8 ✅
- endpointy list/preview/add(walidacja)/deactivate → Task 6 ✅
- frontend: sekcja portfeli, kolumny Acc 24h/7d/30d + Active, add z preview → Task 7 ✅
- scheduler co 15 min + seed wallets → Task 9 ✅
- spike potwierdzenia kształtu + bootstrap → Task 1 ✅
- obsługa błędów (HL nieosiągalny→pomiń; preview 400/422; off-watchlist bez błędu) → Task 5/6/9 ✅

**Placeholder scan:** brak TODO/TBD; cały kod podany. Task 1 to research (świadomie bez kodu).

**Type consistency:** position dict `{coin,side,szi,entry_px,position_value}` + `fetch_positions -> {equity,positions}` spójne (Task 4 ↔ 5 ↔ 6 ↔ 8). `collect_wallet(session, source)`, `compute_consensus(session, min_wallets, ratio)`, `_confidence(position_value, equity)` spójne między tasками i testami. `WalletPosition` pola (Task 3) zgodne z użyciem w 5/6/8. Importy `api.py` (re, func, WalletPosition, fetch_positions) dodane w Task 6. HORIZONS 30d (Task 2) używane przez scorer/`/api/wallets` acc_30d (Task 6).

**Decomposition note:** Tasks 8 (consensus) i 2 (30d) są cuttable bez psucia rdzenia (Tasks 1,3,4,5,6,7,9). Jeśli zakres puchnie — wdrożyć rdzeń, consensus/30d później.
