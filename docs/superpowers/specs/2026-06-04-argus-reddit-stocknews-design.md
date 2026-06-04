# Argus — Increment 4: Reddit + stock-news + asocjacja sektorowa

**Data:** 2026-06-04
**Status:** Design zaakceptowany (brainstorming + analiza usera w `docs/superpowers/plans/analiza planu`)
**Kontekst:** Increment 4 nad Argusem ([[project_argus]]). Cel: zwiększyć recall claimów dodając Reddit i stock-news jako źródła RSS, oraz **asocjację sektorową** (sygnał o sektorze → ticker), bez nowego kolektora i bez LLM.

---

## 1. Cel
Reddit i portale finansowe to kolejne feedy RSS → istniejący `collect_rss` + `extract_claims` je obsłużą. Rozszerzony słownik kierunków (slang WSB/Reddit) + asocjacja sektorowa podnoszą recall, szczególnie dla niszowych akcji z watchlisty, które rzadko padają z nazwy.

## 2. Ustalenia ze spike'u (2026-06-04, z VPS)
- Reddit **`.rss` działa** (200, Atom): `https://www.reddit.com/r/<sub>/.rss`. Reddit **JSON 403** z IP VPS → idziemy RSS.
- Stock-news RSS 200+items: WSJ Markets (`feeds.a.dj.com/rss/RSSMarketsMain.xml`), MarketWatch (`/rss/topstories`, 301→ok), Yahoo Finance (`finance.yahoo.com/news/rssindex`), CNBC (`cnbc.com/id/100003114/device/rss/rss.html`), Seeking Alpha (`seekingalpha.com/feed.xml`).

## 3. Decyzje (po analizie usera)
- **`source_type` / `source_name` bez migracji:** feedy seedowane z `Source.kind`: `"reddit"` (subreddity), `"news"` (portale), krypto-RSS zostaje `"rss"`. `source_type = kind`, `source_name = display_name` — atrybuty Source, dostępne przez `claim.source_id`. Job RSS poszerzony na `kind in ("rss","reddit","news")`.
- **`sectors.yaml` ze strukturą aliasów** (rozszerzalne bez kodu):
  ```yaml
  natural_gas:
    aliases: ["natural gas", "nat gas", "lng", "henry hub", "lng shipping"]
    tickers: [NFE, DLNG]
    confidence: 0.3
  ```
- **Asocjacja sektorowa:** gdy tekst ma kierunek + alias sektora → claim na zmapowanych tickerach z `confidence` sektora (~0.3). **Direct mention/cashtag bije sektorowy** (dedup per symbol — wyższy confidence wygrywa, brak dubli).
- **rule-v2:** rozbudowany słownik kierunków + cashtagi z interpunkcją.
- Watchlista akcji bez zmian (7 tickerów, już scorowalne przez yfinance z Increment 2). Bez nowych tabel/endpointów.

## 4. Architektura / komponenty
- **`config/sources.yaml`** (rozszerzenie): + subreddity (`kind: reddit`) + portale (`kind: news`). Seedowane istniejącym `seed_sources`.
- **`config/sectors.yaml`** (nowy): mapa sektorów (aliases/tickers/confidence) dla 7 akcji.
- **`extract.py` → rule-v2:**
  - `PARSER_VERSION = "rule-v2"`.
  - Rozbudowane `_PATTERNS` (bull: long, calls, bullish, squeeze, breakout, rip(ping), sending, pump, gamma/short squeeze, moonshot, moon, 🚀; bear: short, puts, bearish, dump, crash, rekt, capitulation, selloff, rug (pull), drilling, bloodbath, massacre). Hedge-dampening jak dotąd.
  - Cashtag/ticker matching odporny na interpunkcję (`$NFE`, `($NFE)`, `$NFE..`).
  - **Sygnatura: `extract_claims(text, assets, sector_map=None)`.** Po direct-match (normalny confidence), jeśli `sector_map` podany: dla aliasów obecnych w tekście em ituj claim na `tickers` z `confidence` sektora — tylko dla symboli jeszcze nie złapanych bezpośrednio (dedup per symbol, direct wygrywa).
- **`collectors/rss.py`** (drobna zmiana): wczytaj `sector_map` z `config/sectors.yaml` (raz) i przekaż do `extract_claims`. Reszta bez zmian (dedup itemów, claim+audit, entry_price).
- **`main.py`** (drobna zmiana): `_rss_job` selektuje `Source.kind.in_(["rss","reddit","news"])`; seed `config/sources.yaml` (już) — nowe feedy wjadą przy boot.

## 5. Przepływ
feed (reddit/news/rss) → `collect_rss` → `extract_claims(text, assets, sector_map)` → claimy (direct normalny conf / sektorowe ~0.3) + `claim_audit(parser_version="rule-v2")` → evaluator (1h/24h/7d/30d; akcje przez yfinance) → scorer → ranking źródeł (Reddit vs news vs krypto-RSS rozróżnialne po `kind`).

## 6. Obsługa błędów
- Reddit/feed niedostępny lub pusty → `collect_rss` jest odporny (per-claim try/except na cenę już jest; pusty feed → 0 itemów).
- Brak `config/sectors.yaml` → `sector_map=None`, asocjacja pominięta (tylko direct match).
- Akcja poza godzinami sesji → yfinance zwraca najbliższy close (zaakceptowane w Increment 1).

## 7. Testy (TDD)
- `extract.py`: nowy slang (calls→bull, puts→bear, „short squeeze"→bull, „bloodbath"→bear...); cashtag z interpunkcją (`$NFE`, `($NFE)`); **asocjacja sektorowa** („natural gas looking bullish" + sector_map → bull@0.3 na NFE i DLNG); **direct bije sektor** (jeśli pada `$NFE` i alias gazu → jeden claim na NFE z wyższym conf, bez dubla); brak kierunku → brak claima.
- `collect_rss`: ładuje sector_map i przekazuje (test z mock feed zawierającym alias sektora → claim sektorowy).
- `main`: `_rss_job` łapie kind reddit/news (import/smoke).
- Smoke VPS: po redeploy feedy reddit/news zaciągają itemy; pojawiają się claimy (w tym ew. sektorowe na akcjach).

## 8. Out of scope (roadmapa)
- Increment 5 = likwidacje (twardy sygnał rynkowy, darmowy feed).
- Increment 6 = LLM topic→ticker (dokładniejsza asocjacja; teraz tylko heurystyka).
- Opcjonalne (później): dedup na poziomie claimu (ten sam ticker+kierunek z wielu źródeł), logowanie statystyk ekstraktora (direct vs sektor vs źródło), `base_confidence * source_weight`.
- Literalne kolumny `source_*` na `claims` (zamiast derive z Source) — tylko jeśli zajdzie potrzeba (wymaga migracji).

## 9. Open
- Brak — mechanizm (RSS), atrybucja (per-feed via kind), struktura sectors.yaml i progi ustalone.
