# Argus — Increment 3: śledzenie portfeli Hyperliquid

**Data:** 2026-06-04
**Status:** Design zaakceptowany (brainstorming + analiza usera w `docs/superpowers/plans/analiza planu`)
**Kontekst:** Increment 3 nad Argusem ([[project_argus]]). Cel: śledzić pozycje konkretnych traderów na Hyperliquid jako **sygnały kierunkowe**, które wpadają w istniejącą pętlę wiarygodności — i niech Argus sam zrankinguje whale’i po **trafności kierunkowej**, nie PnL.

---

## 1. Cel
Pozycja tradera (long/short na coinie) = falsyfikowalne twierdzenie kierunkowe → trafia w `claims` → scorer rankinguje portfele per aktywo. Plus agregat „whale consensus" i UI do zarządzania śledzonymi adresami (z podglądem pozycji).

## 2. Ustalenia z API (spike 2026-06-04)
- `POST https://api.hyperliquid.xyz/info {"type":"clearinghouseState","user":"0x.."}` → bez auth. Pozycje w `assetPositions[].position`: `coin`, `szi` (signed: +long/−short), `entryPx`, `leverage`, `positionValue`; equity w `marginSummary.accountValue`. **Dokładny kształt potwierdzić na żywym adresie z pozycją (Task spike).**
- **Brak API leaderboard** → adresy z publicznego trackera (hypurrscan) na bootstrap + dodawanie z frontu.
- 11/14 coinów watchlisty na HL; **brak AEVO/GROK/ALU**.
- 50 req/s, bez klucza.

## 3. Decyzje projektowe (po analizie usera)
- **entry_price = spot w momencie wykrycia** (`get_spot_price`) — mierzymy „gdybyś skopiował gdy MY zobaczyliśmy". Do `claim_audit.parsed_claim` zapisujemy `{wallet_entry_px, detected_px, leverage, position_value, equity}` (oba warianty do późniejszej analizy; bez migracji — reuse JSON).
- **Nie hard-wire do watchlisty:** `wallet_positions` zapisuje WSZYSTKIE pozycje (też off-watchlist, np. HYPE/FARTCOIN — widoczne w podglądzie). Scored `claims` tylko dla coinów obecnych w `assets`. Dodanie aktywa później → przyszłe pozycje automatycznie scorowane (zero przebudowy).
- **confidence = `clamp(position_value/accountValue, 0.5, 0.9)`**; brak equity → `0.7`. NIE leverage.
- **Ranking = directional accuracy** (istniejący `source_asset_scores.hit_rate`/`decayed_score`). PnL tylko do bootstrapu kandydatów.
- **30d horizon dodany system-wide**: `HORIZONS += {"30d": 30 dni}`, `THRESHOLDS += {"30d": 0.08}`. Addytywne — dotyczy też claimów newsowych.

## 4. Architektura / komponenty
- **Źródła:** śledzony portfel = `Source(kind="hyperliquid", handle="0x..", display_name=label)`. Agregat = `Source(kind="derived", handle="whale-consensus", display_name="Whale Consensus")` (seed raz).
- **`wallet_positions` (nowa tabela):** `id, source_id, coin, side(long|short), szi, entry_px, position_value, opened_ts, last_seen_ts, open(bool)`. Stan do diffowania między pollami + źródło podglądu pozycji (incl. off-watchlist).
- **`collectors/hyperliquid.py`:** dla każdego aktywnego `kind=hyperliquid` źródła → `clearinghouseState` → diff vs `wallet_positions`:
  - nowa pozycja LUB flip kierunku w coinie obecnym w `assets` → emit `Claim(method="position", entry_price=spot, confidence=…)` + `ClaimAudit(parsed_claim={…}, parser_version="hyperliquid-v1")`.
  - każda pozycja (też off-watchlist) → upsert do `wallet_positions`; znikła → `open=False`.
  - zmiana rozmiaru bez zmiany kierunku → tylko update, brak nowego claima.
- **Consensus (`agg_consensus`):** po pollu, per coin watchlisty: policz long/short wśród OTWARTYCH pozycji whale’ów; gdy `≥CONSENSUS_MIN_WALLETS` (start 4) i `≥CONSENSUS_RATIO` (0.66) jednej strony I stan się zmienił względem ostatniego → emit `Claim` od źródła „Whale Consensus".
- **Endpointy (`api.py`):**
  - `GET /api/wallets` → lista `kind=hyperliquid` źródeł + `acc_24h/acc_7d/acc_30d` (hit_rate z `source_scores`), `active_positions` (count z `wallet_positions` open), `active`.
  - `GET /api/wallets/preview?address=0x..` → live `clearinghouseState`: walidacja formatu + lista pozycji `[{coin, side, position_value}]` (przed zapisem).
  - `POST /api/wallets {address,label}` → walidacja `^0x[0-9a-fA-F]{40}$`, insert Source (idempotentnie po handle).
  - `POST /api/wallets/{id}/deactivate` → `active=False`.
- **Frontend (sekcja „Śledzone portfele"):** tabela `Wallet | Acc 24h | Acc 7d | Acc 30d | Active | [deactivate]` + formularz dodawania z krokiem **preview** (pokaż pozycje, potem „Zapisz").
- **Scheduler:** job `hyperliquid` co 15 min (poll+diff+consensus).
- **Bootstrap:** `config/wallets.yaml` (adresy z leaderboardu HL via spike + ręczne), seedowane jak `sources.yaml`.

## 5. Przepływ
clearinghouseState → diff(`wallet_positions`) → [coin∈assets] Claim(position) + audit → evaluator(1h/24h/7d/30d) → scorer → `source_(asset_)scores` → `/api/wallets` & overview. Consensus liczony po każdym pollu.

## 6. Obsługa błędów
- Adres bez pozycji / nieosiągalny HL → collector loguje i pomija (jak resilient RSS); preview zwraca 400 „brak danych / zły adres".
- `POST /api/wallets` zły format → 422.
- Pozycja w coinie spoza `assets` → tylko `wallet_positions` (bez claima), bez błędu.

## 7. Testy (TDD)
- collector: nowa pozycja w watchlist-coinie → 1 claim + wallet_positions; brak zmiany → 0 claimów; flip → nowy claim; pozycja off-watchlist → wallet_positions, 0 claimów; confidence = position_value/equity (i fallback 0.7).
- consensus: 4/6 long SOL → 1 consensus claim; brak progu → 0.
- endpointy wallets: preview (mock HL), add (walidacja + idempotencja), list (z accuracy), deactivate.
- evaluator/scorer: 30d horizon liczony (rozszerzenie istniejących testów lub nowy).
- Front: smoke + ręcznie (tunel).

## 8. Kolejność / cuttable
Rdzeń (collector + wallet_positions + claimy + endpointy + front + bootstrap) najpierw; **consensus** i **30d horizon** jako osobne, późniejsze taski (można odciąć bez psucia rdzenia).

## 9. Out of scope
- Auto-discovery aktywów (dynamiczne dodawanie coinów spoza watchlisty do scoringu) — architektura gotowa, ale ręczne dodanie aktywa zostaje na później.
- Spot/on-chain portfele (tylko perpy HL).
- Paid API. Auth (dostęp przez tunel).

## 10. Open
- Dokładny kształt `assetPositions[].position` — potwierdzić na żywym adresie (Task spike). Reszta ustalona.
