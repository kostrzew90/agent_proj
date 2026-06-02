# Argus — agent śledzenia trendów z samonauką wiarygodności źródeł

**Data:** 2026-06-02
**Status:** Design (zaakceptowany do zapisu, oczekuje review spec)
**Autor:** brainstorming Opus + user

---

## 1. Problem / cel

Jako trader/obserwator rynku krypto (i lekko giełdy) chcę agenta, który **24/7 śledzi wąski watchlist**, zbiera twierdzenia kierunkowe z wielu źródeł i **uczy się, którym źródłom ufać** — mierząc ich historyczną trafność względem realnego ruchu ceny. Output: web dashboard z trend-leanem per aktywo i rankingiem wiarygodności źródeł.

**Definicja samonauki (kluczowa):** system nie uczy się "czy ma rację o rynku", tylko **komu ufać**. Źródło robi falsyfikowalne twierdzenie kierunkowe (z timestampem), system po horyzoncie sprawdza cenę (prawda gruntowa) i aktualizuje wiarygodność źródła. LLM jest **dodatkiem**, nie rdzeniem pipeline'u.

**Niniejszy dokument NIE jest poradą finansową.** Output = meta-analiza informacji, nie rekomendacja transakcyjna.

## 2. Cele i nie-cele

### Cele (v1 MVP)
- Pełny mierzalny cykl: `claim → outcome → source score → ranking`.
- Wiarygodność per (źródło, aktywo, horyzont), nie tylko globalna.
- Wąski watchlist (~10–20 krypto + kilka spółek/indeksów; crypto-first).
- Web dashboard: trend-lean per aktywo (kierunek + intensywność), leaderboard źródeł, ostatnie twierdzenia + ich rozliczenie, wykresy trafności.
- Niezależny stack Docker na Oracle VPS, 24/7.

### Nie-cele (explicite poza zakresem)
- ❌ Wykonywanie transakcji / składanie zleceń / zarządzanie portfelem.
- ❌ Multi-agent (CrewAI/AutoGen/LangGraph), nocne mega-syntezy LLM.
- ❌ Scraping X/Twitter (zablokowany Cloudflare u usera).
- ❌ Głębokie feedy giełdowe — akcje w v1 tylko z RSS/Reddit (lekko).
- ❌ Porady finansowe.
- ❌ Coinglass jako oceniane źródło — wyłącznie **market context** (overlay).

## 3. Architektura

Niezależny stack Docker na Oracle VPS. LLM = dodatek.

```
Collectors            Claim Extractor        Storage              Analytics             UI
─────────             ──────────────         ───────              ─────────             ──
price (CG/Binance) ┐                       ┌─ prices                 Outcome Evaluator ┐
rss (feedparser)   ├─► [inline regex f.1] ─►├─ items                 Source Scorer      ├─► FastAPI + React
hyperdash (pozycje)┤   [rule-based f.1.5]  ├─ claims                 Asset Trend-lean   ┘   (dashboard)
[reddit  — faza 3] ┘   [LLM — faza 2]      ├─ claim_audit
[coinglass — faza 3, kontekst/overlay]     └─ outcomes
```

Każdy komponent = osobny, testowalny moduł z jasnym interfejsem:

- **Collectors** — po jednym module na źródło, piszą do `items`/`prices`. Idempotentne (dedup po `external_id`). Hyperdash: pozycja long/short = gotowe twierdzenie kierunkowe (zero LLM).
- **Claim Extractor** — fazowo: inline regex (faza 1) → rozbudowane reguły/słowniki (faza 1.5) → LLM (faza 2). Każdy zapis claima loguje do `claim_audit` (raw_text, parsed_claim, parser_version).
- **Outcome Evaluator** — job: dla twierdzeń po horyzoncie dociąga cenę **on-demand z historical API** (CoinGecko/Binance), liczy `return_pct`, ustala `hit`, zapisuje `outcomes` (osobny wiersz per horyzont 1h/24h/7d).
- **Source Scorer** — agreguje `outcomes` → `source_asset_scores` (granularne) i `source_scores` (rollup), z wygaszaniem czasowym i korektą na małą próbkę.
- **LLM Router** (faza 2) — cienki moduł: OpenRouter free → Gemini free → płatny eskalacyjnie, twardy cap budżetu (wzorzec llm-proxy z Hermesa, ale bez Mac Studio).
- **Dashboard** — FastAPI (JSON API) + React SPA (Vite) serwowane statycznie.
- **Scheduler** — za cienkim interfejsem `scheduler/` (faza 1: APScheduler w procesie API; later: Celery/Temporal/Prefect bez przebudowy logiki).

## 4. Model danych (warstwa abstrakcji DB — Postgres lub SQLite)

- **`assets`** — watchlist: `symbol`, `kind` (crypto|stock), `coingecko_id`/`binance_symbol`, `active`.
- **`sources`** — `id`, `kind` (rss|hyperdash|reddit|onchain), `handle` (URL/subreddit/trader), `display_name`, `active`.
- **`items`** — `id`, `source_id`, `external_id` (dedup), `title`/`text`/`url`, `published_at`, `fetched_at`.
- **`claims`** — `id`, `source_id`, `item_id` (null dla pozycji), `asset`, `direction` (bull|bear|neutral), `target_price` (null), `confidence` (0–1), `method` (position|rule|llm), `entry_price`, `entry_ts`, `status`.
- **`claim_audit`** — `id`, `claim_id`, `raw_text`, `parsed_claim` (json), `parser_version`. → re-parse historii po zmianie reguł bez ponownego pobierania źródeł.
- **`prices`** — `asset`, `ts`, `price` (**rzadki** cache prawdy gruntowej: tylko punkty entry i horyzontów, dociągane on-demand z historical API — nie gęsty polling co 5 min).
- **`outcomes`** — `id`, `claim_id`, `horizon` (1h|24h|7d), `eval_ts`, `price_at_horizon`, `return_pct`, `hit` (bool), `resolved_at`.
- **`source_asset_scores`** — `source_id`, `asset`, `horizon`, `n_claims`, `n_hits`, `hit_rate`, `avg_return`, `decayed_score`, `updated_at`.
- **`source_scores`** — rollup: `source_id`, `horizon`, `n_claims`, `hit_rate`, `avg_return`, `decayed_score`, `updated_at`.

## 5. Scoring (formuły)

### Hit (per horyzont)
Progi `θ_h` konfigurowalne per horyzont (start: 1h ±0.5%, 24h ±1.5%, 7d ±4%):
- bull → hit gdy `return_pct ≥ +θ_h`
- bear → hit gdy `return_pct ≤ −θ_h`
- neutral → hit gdy `|return_pct| < θ_h`

### Score źródła (per source/asset/horyzont)
Wygaszany czasowo hit-rate z korektą Bayesowską na małą próbkę:
- `decayed_score = (Σ w_i·hit_i + α) / (Σ w_i + α + β)`, gdzie `w_i = exp(−Δt_i/τ)` (świeższe twierdzenia ważą więcej), prior `Beta(α,β)` z `α=β=2` (ściąga małą próbkę do 0.5).
- `source_scores` = agregat `source_asset_scores` ważony `n_claims`.

### Waga twierdzenia
`claim_weight = effective_source_score × confidence × freshness`
- `effective_source_score` = `source_asset_score` jeśli `n_claims ≥ k` (start k=5), inaczej blend z `source_scores`.
- `freshness = exp(−Δt/τ)` od `entry_ts`.

### Trend-lean (per aktywo/horyzont)
`lean = Σ (direction_sign × effective_source_score × confidence × freshness)` po aktywnych (niewygasłych) twierdzeniach.
Dashboard pokazuje **kierunek** (znak) i **intensywność** (moduł).

### Confidence — skąd
- `position` (Hyperdash): default + ew. korekta o wielkość/leverage pozycji.
- `rule`: per siła wzorca ("long BTC 100k target" > "BTC might pump").
- `llm`: model zwraca confidence.

## 6. Stack i deployment

- Python 3.12, FastAPI, SQLAlchemy (abstrakcja DB), APScheduler, httpx, feedparser.
- React (Vite) → statyki serwowane przez FastAPI.
- Docker Compose: `db` + `app` (API + scheduler). 2 kontenery — lekko na VPS.
- Klucze LLM i DB w `.env`. Watchlist + sources seedowane SQL/configiem.

### Decyzja storage (zatwierdzona)
- **VPS: Oracle Ampere A1 (24GB RAM).**
- **DB: local Postgres w Dockerze na A1** (co-located z app). $0, zero latencji, brak limitów free-tier ani cold-startów — wygrywa dla 24/7 pollera.
- Backup: docker volume + cron `pg_dump`.
- Warstwa SQLAlchemy izoluje wybór — przejście na **Neon** (serverless) to jednolinijkowy switch connection-stringa w `.env`, bez zmian w kodzie. Opcja na later, jeśli zechcesz managed backups/branching/dostęp z wielu miejsc.

## 7. Fazowanie i kolejność implementacji

Kolejność celowo dowodzi **pełny cykl na RSS** zanim dojdzie Hyperdash:

- **Faza 0 (spike):** zweryfikuj dostęp do danych **Hyperdash** (API czy scraping — realne ryzyko, może nie być publicznego API) i **Coinglass** (freemium API); ustal finalny watchlist.
- **Faza 1 (pełny cykl na RSS):**
  1. Schema DB (wszystkie tabele, w tym `claim_audit`, `source_asset_scores`).
  2. Price module (CoinGecko/Binance): cena spot przy tworzeniu claima (`entry_price`) + historical lookup przy ewaluacji horyzontu.
  3. RSS collector + **inline regex** ekstrakcja prostych twierdzeń ("bullish/bearish/long/short on X").
  4. Outcome evaluator (1h/24h/7d).
  5. Source scoring (`source_asset_scores` + `source_scores`).
  6. Dashboard MVP (top źródła, top aktywa, trafność, trend-lean).
- **Faza 1.5:** Hyperdash collector (position→claim); rozbudowane reguły/słowniki; walidacja scoringu na realnych danych.
- **Faza 2:** LLM router (free→paid) + LLM-ekstrakcja twierdzeń z niejednoznacznego tekstu.
- **Faza 3:** Reddit, overlay Coinglass (market context), alerty (opcjonalnie Telegram), akcje (RSS/Reddit), dzienny digest.

## 8. Ryzyka

- **Hyperdash access** — może wymagać scrapingu / brak API. Spike w Fazie 0; jeśli niedostępne, przesuwamy lub szukamy alternatywy. Cykl i tak działa na RSS.
- **VPS RAM (Micro 1GB)** — Postgres+app+React ciasno. Mitigacja: SQLite+litestream, statyczny build React.
- **Jakość regex-ekstrakcji** — fałszywe twierdzenia psują scoring. Mitigacja: `claim_audit` + re-parse, konserwatywne wzorce na start, walidacja w 1.5.
- **Free-tier rate limits LLM** — dotyczy dopiero fazy 2; router z fallbackiem + cap budżetu.

## 9. Open Questions (do potwierdzenia przed Fazą 1)

1. ✅ **VPS + storage** — Oracle Ampere A1 + local Postgres w Dockerze. (Rozstrzygnięte.)
2. **Watchlist** — user dostarcza własną listę tickerów (seed do tabeli `assets`); wymagana przed odpaleniem Fazy 1, nie blokuje planu.
3. ✅ **Nazwa** — "Argus". (Potwierdzone.)
