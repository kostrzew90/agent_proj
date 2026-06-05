# Argus — Increment 7: HyperStats leaderboard → auto-discover tracked wallets

**Data:** 2026-06-05
**Status:** Design zaakceptowany (brainstorming + analiza usera w `docs/superpowers/plans/analiza planu`)
**Kontekst:** Increment 7 nad Argusem ([[project_argus]], `argus/STATUS.md`). Wypełnia lukę z Inc 3 (Hyperliquid nie ma API leaderboard → ręcznie seedowaliśmy 2 adresy). Recon znalazł darmowe JSON API → auto-odkrywanie top-traderów bez przeglądarki.

---

## 1. Cel
Automatycznie odkrywać dobrych traderów Hyperliquid (leaderboard) i dodawać ich jako śledzone portfele, żeby istniejąca pętla z Inc 3 ciągnęła ich pozycje → claimy. Bez przeglądarki, bez zależności od Hermesa/laptopa.

## 2. Ustalenia z recon (2026-06-05)
- **HyperStats backdoor JSON API:** `GET https://v2-api.hyperstats.org/api/traders?limit=N` — bez auth, bez rate-limitu, bez Cloudflare. Pola: `address, grade (S+/A/...), totalPnl, winRate, pnl24h, pnl7d, totalVolume, totalTrades, openPositions, accountValue, mainToken, lastActivityAt (ISO)`.
- Wszystkie dashboardy (hyperdash/dexly/hypurrscan/official) to JS-SPA wymagające realnego Chrome — **HyperStats API czyni je zbędnymi** dla tego celu. **Nieoficjalne** API (brak SLA) → kolektor musi być odporny.
- HL nadal nie ma oficjalnego leaderboardu; HyperStats to obejście.

## 3. Decyzje (po analizie usera)
- **Filtr jakości** (nie sami hazardziści): trader przechodzi gdy
  `winRate ≥ ARGUS_HYPERSTATS_MIN_WINRATE (0.5) AND totalTrades ≥ ARGUS_HYPERSTATS_MIN_TRADES (50) AND lastActivityAt ≥ now−14d AND (totalPnl > 0 OR grade∈{A*,S*})`.
- **Insert-only do `Source`** z jawnym logowaniem 3 przypadków: istnieje+aktywny→skip; istnieje+nieaktywny→log „ręcznie wyłączony, pomijam"; nowy→create. **Nigdy nie modyfikuje istniejących** (szanuje ręczne deaktywacje usera).
- **Grade/PnL z HyperStats = tylko bootstrap doboru.** Ranking po trafności robi scorer Argusa (outcome).
- **Obserwowalność:** każdy przebieg loguje `{fetched, passed_filter, added, skipped_existing, skipped_inactive, errors}`.
- **Bez nowej tabeli/endpointu** — auto-dodane portfele pojawiają się w istniejącym `/api/wallets` + panelu; pozycje/claimy przez istniejący `_hyperliquid_job` (Inc 3).
- Job raz dziennie (1 request).

## 4. Architektura / komponenty
- **`argus/argus/collectors/hyperstats.py`:**
  - `fetch_leaderboard(limit=100) -> list[dict]` — httpx GET, parsuje `traders[]` (timeout, raise na błąd HTTP).
  - `_passes_filter(t, min_win_rate, min_trades, max_age_days, now) -> bool` — czysta funkcja (testowalna) z regułą z §3.
  - `sync_top_traders(session, top_n, min_win_rate, min_trades, max_age_days) -> dict` — fetch → filtr → dla top-N upsert insert-only `Source(kind="hyperliquid", handle=address.lower(), display_name=f"HL {grade} {address[:8]}")`; zwraca + loguje stats dict.
- **`argus/argus/main.py`:** nowy job `_hyperstats_job` (woła `sync_top_traders` w try/except — błąd nie wywala schedulera) + `sched.add_interval("hyperstats", _hyperstats_job, minutes=1440)` (raz dziennie). Reużywa istniejący `_hyperliquid_job` (15 min) do pozycji.
- **`argus/.env.example`:** `ARGUS_HYPERSTATS_TOP_N=20`, `ARGUS_HYPERSTATS_MIN_WINRATE=0.5`, `ARGUS_HYPERSTATS_MIN_TRADES=50`.

## 5. Przepływ
HyperStats `/api/traders` → filtr jakości → top-N adresów → insert-only `Source(kind=hyperliquid)` → (istniejący Inc-3 `collect_wallet`) `clearinghouseState` → position-claimy → evaluator/scorer → `/api/wallets` ranking po trafności.

## 6. Obsługa błędów
- HyperStats nieosiągalny / zła odpowiedź / timeout → `fetch_leaderboard` rzuca; `_hyperstats_job` łapie, loguje `errors`, nie wywala schedulera. Następny dzień retry.
- Zła data `lastActivityAt` → trader pomijany (traktowany jak nie-przechodzący), log.
- Adres już śledzony → insert-only (skip, z logiem wg przypadku).

## 7. Testy (TDD)
- `fetch_leaderboard`: mock httpx → parsuje listę traderów; respektuje limit param.
- `_passes_filter`: przechodzi dobry trader; odrzuca: winRate<próg, totalTrades<50, lastActivity>14d temu, (pnl≤0 i grade poza A/S).
- `sync_top_traders`: nowy adres → Source utworzony (kind=hyperliquid); istniejący aktywny → nie duplikuje; istniejący nieaktywny → NIE reaktywuje; zwraca poprawny stats dict. (mock fetch_leaderboard).
- `main`: import + `_hyperstats_job` istnieje, scheduler ma job „hyperstats".

## 8. Out of scope
- Browser-human dla X/Twitter (osobny przyszły increment — tam API naprawdę brak).
- Snapshot leaderboardu / historia grade w osobnej tabeli (na razie tylko seed źródeł).
- Auto-deaktywacja portfeli spadających z leaderboardu (insert-only; czyszczenie ręczne lub później).

## 9. Open
- Brak — źródło (HyperStats JSON), filtr, insert-only+logi, job dzienny ustalone.
