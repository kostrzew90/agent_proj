# Argus — Increment 5: likwidacje (market-context)

**Data:** 2026-06-04
**Status:** Design zaakceptowany (brainstorming + analiza usera w `docs/superpowers/plans/analiza planu`)
**Kontekst:** Increment 5 nad Argusem ([[project_argus]], `argus/STATUS.md`). Cel: dodać darmowy feed **zrealizowanych likwidacji** (Binance futures) jako **market-context** — osobny od pętli claimów/wiarygodności.

---

## 1. Cel
Likwidacje to twardy, obiektywny sygnał (gdzie/ile się likwiduje). Strumień `forceOrder` Binance → tabela `liquidations` → agregacja per aktywo (long-liq vs short-liq) → panel na dashboardzie. **NIE wpływa na scoring** (to nie claim, to kontekst).

## 2. Ustalenia ze spike'u (2026-06-04, z VPS)
- `wss://fstream.binance.com/ws/!forceOrder@arr` osiągalny z VPS (101). Schema: `{"o":{"s":symbol,"S":"SELL|BUY","p":price,"q":qty,"T":ts}}`. **SELL = zlikwidowany long, BUY = zlikwidowany short.** Pola liczbowe przychodzą jako **stringi**.
- **Brak darmowego REST** dla likwidacji (404/auth) → websocket to jedyna darmowa droga. Bybit WS = backup (out of scope).
- Kontener potrzebuje pip `websockets`. VPS go nie ma — dodajemy do `requirements.txt`.

## 3. Decyzje (po analizie usera)
- **Osobny kontener `liq-listener`** reużywający obraz `app` (bez drugiego Dockerfile): `build: .`, `command: python -m argus.liquidations.listener`, ten sam Postgres.
- **Oddzielenie od pętli claimów** — zero wpływu na claims/scoring.
- **Niezawodność WS:** keepalive przez lib `websockets` (`ping_interval`/`ping_timeout` ustawione — Binance pinguje, lib auto-pong); auto-reconnect z exponential backoff; **circuit breaker** (≥5 fail/10min → dłuższy backoff + log WARNING jako alert); log czasu rozłączenia.
- **Tylko watchlist** (mapowanie po `binance_symbol`, case-insensitive) — reszta rynku odfiltrowana.
- **Retencja:** prune `liquidations` starszych niż 30 dni (w istniejącym dziennym jobie app).

## 4. Architektura / komponenty
- **`argus/argus/liquidations/parser.py`** — `parse_force_order(msg: dict, symbol_to_asset: dict) -> dict | None`. Czysta funkcja: czyta `msg["o"]`, mapuje `s` (upper, case-insensitive) → asset; jeśli brak na watchliście → `None`. `side`: SELL→`"long_liq"`, BUY→`"short_liq"`. `notional_usd = float(p)*float(q)`. Zwraca `{asset, raw_symbol, side, price, qty, notional_usd, ts}`.
- **`argus/argus/liquidations/listener.py`** — `run()`: ładuje `symbol_to_asset` z DB (assets z `binance_symbol`), pętla asyncio websockets → `!forceOrder@arr`, dla każdej wiadomości `parse_force_order` → insert (batch co ~1s lub co N rekordów). Reconnect+backoff+circuit breaker. Entrypoint `python -m argus.liquidations.listener`.
- **`models.py` → `Liquidation`**: `id, asset(FK), exchange("binance"), side, price, qty, notional_usd, ts, raw_symbol, created_at`. Indeksy: `(asset, ts desc)`, `(ts desc)`.
- **`api.py`**:
  - `GET /api/liquidations?window=24h` (`1h|4h|24h|7d`) → per aktywo `{asset, long_liq_usd, short_liq_usd, count}`.
  - `GET /api/liquidations/largest?window=24h&min_notional=100000` → lista pojedynczych dużych likwidacji (asset, side, notional_usd, price, ts).
- **`web/`** — panel „Likwidacje (24h)": słupki per aktywo (czerwony=long-liq, zielony=short-liq), tooltip z USD; lista największych. Selektor okna.
- **`requirements.txt`** + `websockets`. **`docker-compose.yml`** + usługa `liq-listener`.
- **`main.py`** — `_score_job` (lub nowy mały job) woła `prune_liquidations(session, days=30)`.

## 5. Przepływ
Binance WS `forceOrder` → `parse_force_order` (filtr watchlist) → `liquidations` (insert, kontener liq-listener) → `/api/liquidations*` (agregacja okna, kontener app) → panel. Niezależne od claims/outcomes/scores.

## 6. Obsługa błędów
- Rozłączenie WS → reconnect z backoff; po serii błędów circuit breaker (dłuższy sleep + log WARNING). Log: czas rozłączenia.
- Nieznany/niewatchlistowy symbol → `parse_force_order` zwraca `None` (pomijany).
- Zła/niekompletna wiadomość → try/except, log, pomiń (nie wywal pętli).
- liq-listener crash → restartowany przez Docker; nie dotyka API.

## 7. Testy (TDD)
- `parse_force_order`: SELL→long_liq, BUY→short_liq; pola jako stringi → float; nieznany symbol → None; case-insensitive (`btcusdt`); notional = price*qty.
- `/api/liquidations`: agregacja per aktywo dla różnych okien (seed kilku Liquidation z różnymi ts; window 1h vs 24h zwraca różne sumy).
- `/api/liquidations/largest`: filtr `min_notional` + okno.
- `prune_liquidations`: usuwa >30 dni, zostawia świeższe.
- Pętla WS (sieć) NIE unit-testowana — weryfikacja w smoke na VPS (czy liq-listener łapie zdarzenia, czy `liquidations` rośnie).

## 8. Out of scope
- Predykcyjny heatmap (płatny Coinglass).
- Bybit/OKX (backup na później; tabela ma `exchange` na przyszłość).
- Markery likwidacji na świecach, sparkline trendu (opcjonalnie później).
- REST-fallback (brak darmowego REST).

## 9. Open
- Brak — źródło (Binance WS), architektura (osobny kontener), schema, okna i retencja ustalone.
