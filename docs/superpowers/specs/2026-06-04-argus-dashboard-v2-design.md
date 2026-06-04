# Argus — Dashboard v2 (overview + drill-down ze świecami)

**Data:** 2026-06-04
**Status:** Design zaakceptowany (brainstorming)
**Kontekst:** Increment 2 nad wdrożonym Argusem (Faza 1 — [[project_argus]], spec `2026-06-02-argus-trend-credibility-agent-design.md`). Cel: uczynić aktywność agenta **weryfikowalną wzrokowo** i naprawić UX horyzontu.

---

## 1. Problem / cel

Obecny dashboard to płaskie tabele; zmiana horyzontu „nic nie zmienia" gdy 24h/7d nie dojrzały (cicha pustka), a akcje w ogóle się nie pokazują (brak claimów → `trend_lean` ich pomija). User chce **widzieć co się działo historycznie**: cena jako świece + naniesione „kto co twierdził i kiedy", z możliwością wejścia w aktywo.

## 2. Cele (ten increment)
- **Overview** z klikalną listą wszystkich scorable aktywów (krypto + akcje), rankingiem źródeł, selektorem horyzontu domyślnie `1h` i jawnym **empty-state**.
- **Drill-down per aktywo**: wykres świecowy (TradingView Lightweight Charts) + **markery claimów** (▲bull/▼bear, kolor wg wiarygodności źródła, tooltip ze źródłem + hit/miss) + ranking źródeł dla tego aktywa + lista jego claimów z wynikiem.
- **Akcje i aktywa bez claimów widoczne** (lean=0), z wykresem z yfinance.
- Naprawa: zmiana horyzontu zawsze daje czytelny rezultat (dane albo komunikat).

## 3. Nie-cele (roadmapa — kolejne incrementy, bez paid API)
- ❌ Portfele Hyperliquid (Increment 3, najwyższy sygnał).
- ❌ Reddit + stock-news (Increment 4).
- ❌ Likwidacje Binance `forceOrder` (Increment 5).
- ❌ Build-step/React (zostajemy przy vanilla + CDN).
- ❌ Auth na dashboardzie (dostęp przez tunel SSH; port 8080 zamknięty na VPS).

## 4. Architektura

Rozszerzenie istniejącego stacku (`argus/`). Bez nowych kontenerów.

- **`argus/argus/charts.py`** (nowy) — `get_candles(asset, interval, limit) -> list[dict]` zwraca OHLC `{time, open, high, low, close}` (time = epoch sekundy). Dispatch po `asset.kind`: crypto → Binance `/api/v3/klines`; stock → yfinance `Ticker.history`. Wzorzec jak `prices.py`.
- **`argus/argus/api.py`** (rozszerzenie):
  - `GET /api/candles?asset=BTC&interval=1h&limit=168` → proxy do `charts.get_candles`. Błąd pobrania → 502 + `{"error": ...}`.
  - `GET /api/asset/{symbol}?horizon=1h` → `{claims:[...], sources:[...]}`: claimy aktywa (z nazwą źródła, kierunkiem, confidence, entry_ts oraz `hit` jeśli istnieje Outcome dla tego horyzontu) + `source_asset_scores` dla aktywa+horyzontu.
  - `GET /api/assets` (zmiana) — zwraca **wszystkie scorable aktywa**, lean z `trend_lean` lub 0 gdy brak otwartych claimów. (`trend_lean` zostaje czyste; merge robi endpoint.)
- **`argus/argus/web/`** (przepisanie):
  - `index.html` — dodaje `<script>` CDN Lightweight Charts, kontener overview + sekcja detalu (ukryta do kliknięcia).
  - `app.js` — overview (fetch `/api/assets`, `/api/sources`; horyzont default 1h; empty-state), klik aktywa → fetch `/api/candles` + `/api/asset/{symbol}`, render świec + `series.setMarkers(...)` z claimów.

### Domyślne parametry świec
- crypto: `interval=1h`, `limit=168` (7 dni kontekstu).
- stock: `interval=1d`, `limit=90` (~kwartał). Mapowanie interwału po `kind` w `get_candles`.

## 5. Przepływ danych
1. Overview ładuje `/api/assets?horizon=1h` (wszystkie aktywa + lean) i `/api/sources?horizon=1h`.
2. Zmiana horyzontu → ponowny fetch; jeśli `sources`/lean puste dla horyzontu → empty-state „Brak dojrzałych danych dla {h} (potrzeba ~{h} od pierwszych claimów)".
3. Klik aktywa → równolegle `/api/candles` (OHLC) i `/api/asset/{symbol}` (claimy+źródła). Markery: dla każdego claima marker w `entry_ts` (shape arrowUp/arrowDown wg kierunku, kolor wg `decayed_score` źródła, tekst = `display_name` + ew. ✓/✗).

## 6. Obsługa błędów
- Candle fetch (Binance/yfinance) rzuca → endpoint 502 `{"error":...}`; UI pokazuje „Nie udało się pobrać świec dla {symbol}". Nie wywala reszty strony.
- Aktywo `kind in {index,macro}` (nie ma providera cen) → `/api/candles` zwraca 400 „brak źródła cen"; w UI te aktywa nie są klikalne do wykresu.
- Frontend: każdy fetch w `try/catch`, render sekcji niezależnie (błąd jednej nie blokuje innych).

## 7. Testy
- `charts.get_candles`: crypto (mock Binance klines) i stock (mock yfinance) → poprawny kształt OHLC; nieobsługiwany kind → ValueError.
- `/api/candles`: 200 + lista dla crypto (mock); 502 gdy provider rzuca.
- `/api/asset/{symbol}`: zwraca claimy z hit z Outcome + source_asset_scores (seed w teście).
- `/api/assets`: zawiera aktywo scorable bez claimów (lean 0) — regresja na „akcje widoczne".
- Frontend: smoke (GET / 200, /app.js 200, CDN script tag obecny) + ręczna weryfikacja na VPS przez tunel.

## 8. Open questions
- Brak — parametry świec i semantyka markerów ustalone powyżej.
