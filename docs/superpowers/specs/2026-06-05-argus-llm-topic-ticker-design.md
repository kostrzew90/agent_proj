# Argus — Increment 6: LLM topic→ticker (gap-fill)

**Data:** 2026-06-05
**Status:** Design zaakceptowany (brainstorming + analiza usera w `docs/superpowers/plans/analiza planu`)
**Kontekst:** Increment 6 nad Argusem ([[project_argus]], `argus/STATUS.md`). Pierwsza warstwa LLM: semantyczna ekstrakcja topic→ticker dla itemów, których heurystyka `rule-v2` nie złapała. Tight & cheap: gap-fill + cache + free-first.

---

## 1. Cel
Gdy `rule-v2` nie znajdzie claima w itemie (brak słowa-klucza/tickera/sektora), LLM próbuje wydobyć semantyczne powiązanie narracja→ticker (np. „Fed sygnalizuje cięcia" → BTC/ETH bull). Claimy LLM lecą tym samym torem evaluator→scorer (method=`llm`), więc **outcome jest ich realnym sędzią**.

## 2. Decyzje (po analizie usera)
- **Provider:** router **free→paid**, paid **gated env** (`ARGUS_LLM_ALLOW_PAID`, default off). Gemini 2.0 Flash (free) primary → OpenRouter free → opcj. paid. Klucze w `argus/.env` (VPS): `GEMINI_API_KEY`, `OPENROUTER_API_KEY`.
- **Gap-fill INLINE** w `collect_rss` (nie osobny job): `if not rule_claims: llm_claims = extract_claims_llm(...)`. Bez nowego schedulera/tabeli „processed".
- **LLM NIE zwraca confidence** — zwraca `{asset, direction, reasoning}`. Kod nadaje stałe `LLM_DEFAULT_CONFIDENCE = 0.35`.
- **reasoning tylko w `ClaimAudit`** (`parser_version="llm-v1"`, `parsed_claim={asset,direction,reasoning,...}`) — poza scoringiem; do debug/explainability/eval.
- **Cache `llm_cache`** po `text_hash` (przechowuje też PUSTY wynik) — dedup tych samych tytułów w wielu feedach (60-80% mniej calli) + rola „już przetworzone".
- **Wąski prompt + grounding gate** — explicite dozwolone aktywa + mapowania sektorowe; „claim tylko gdy bezpośrednie/bardzo silne uzasadnienie w tekście; słabe/spekulacyjne → pusta lista". Walidacja: odrzuca tickery spoza watchlisty, kierunek ∈ {bull,bear,neutral}.
- **Judge — ODŁOŻONY** (Increment 7/8, gdy będą metryki method=llm). Obrona jakości: walidacja + niski confidence + grounding gate + outcome-scoring.
- **Metryki (log per przebieg):** gap-rate, cache hit-rate, LLM success-rate (≥1 claim), śr. latencja.

## 3. Architektura / komponenty
- **`argus/argus/llm/router.py`** — `call_llm(prompt, system="", max_tokens=512, tier="medium") -> str`. Łańcuch: Gemini free (REST `generativelanguage.googleapis.com`) → OpenRouter free (`openrouter.ai/api/v1/chat/completions`) → paid (tylko gdy `ARGUS_LLM_ALLOW_PAID` i pod tygodniowym capem `ARGUS_LLM_WEEKLY_BUDGET_USD`, tracking sumy w tabeli `llm_spend`). httpx, timeout per próba, retry/log. Brak klucza danego providera → pomiń go w łańcuchu.
- **`argus/argus/llm/extractor.py`** — `LLM_DEFAULT_CONFIDENCE=0.35`, `PROMPT_VERSION="llm-v1"`; `build_prompt(assets, sector_map)`, `extract_claims_llm(text, assets, sector_map) -> list[ParsedClaim]`: woła router, parsuje ścisły JSON `[{asset,direction,reasoning}]`, waliduje (asset∈watchlist, direction poprawny), nadaje confidence=0.35, reasoning trzymane do audytu. Zły JSON / brak → `[]`.
- **`argus/argus/llm/cache.py`** — `cache_get(session, text_hash)`, `cache_put(session, text_hash, result)`. Tabela `llm_cache(text_hash PK, result_json, created_at)`; pusty wynik = `[]` zapisany.
- **`models.py`**: `LlmCache(text_hash, result_json, created_at)`, `LlmSpend(id, week, usd, updated_at)` (prosty cap).
- **`collectors/rss.py`** (zmiana): po `extract_claims` (rule), jeśli `[]` → `text_hash = sha256(text)`; `cache_get` → jeśli miss, `extract_claims_llm` + `cache_put`; utwórz `Claim(method="llm")` + `ClaimAudit(parser_version="llm-v1", parsed_claim z reasoning)` dla wyników. entry_price jak dotąd (`get_spot_price`, resilient try/except). Loguj metryki przebiegu.
- **Config/.env:** `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `ARGUS_LLM_ALLOW_PAID=false`, `ARGUS_LLM_WEEKLY_BUDGET_USD=0`, `ARGUS_LLM_PAID_MODEL` (np. `openai/gpt-4o-mini` przez OpenRouter).
- Bez nowej zależności (httpx już jest). Bez osobnego kontenera/joba.

## 4. Przepływ
collect_rss item → `extract_claims` (rule-v2) → jeśli puste: `text_hash` → `llm_cache` (hit→użyj; miss→`extract_claims_llm`→router free→paid→zapis cache) → claimy `method=llm`, conf 0.35, reasoning do audit → evaluator(1h/24h/7d/30d) → scorer (ranking; method rozróżnialny).

## 5. Obsługa błędów
- Brak kluczy / wszystkie free padły i paid off → `extract_claims_llm` zwraca `[]` (gap zostaje pusty, bez wywału collect_rss).
- Zły JSON z LLM → `[]` + log warning.
- Halucynowany ticker (poza watchlistą) → odrzucony.
- Timeout LLM → pomiń item (log), bez blokowania feedu.
- Cache miss-storm zabezpieczony przez throttle (limit LLM-calli per przebieg, np. `ARGUS_LLM_MAX_PER_RUN=30`).

## 6. Testy (TDD)
- `router`: free→paid fallback (mock httpx: Gemini error → OpenRouter; oba free padły + paid off → wyjątek/None); paid gated env; cap blokuje paid.
- `extractor`: poprawny JSON → claimy z confidence=0.35 (NIE z LLM); halucynowany ticker odrzucony; „no clear link"/zły JSON → `[]`; reasoning zachowany.
- `cache`: put/get round-trip; pusty wynik cache'owany (drugi call nie woła LLM).
- `collect_rss` gap-fill: rule puste → LLM wołany (mock) → claim method=llm; rule niepuste → LLM NIE wołany; cache hit → LLM NIE wołany.
- Task 0 spike: Gemini free / OpenRouter free osiągalny z VPS + zwraca sensowny JSON na realnym tytule (wymaga kluczy w .env).

## 7. Prerequisite
`GEMINI_API_KEY` + `OPENROUTER_API_KEY` w `argus/.env` na VPS (sekrety — user wstawia; .env gitignored). Bez tego LLM no-op (gap zostaje pusty).

## 8. Out of scope
- LLM-judge (Increment 7/8 — gdy będą metryki method=llm).
- LLM na wszystkich itemach (tylko gap-fill).
- Off-watchlist auto-discovery aktywów.
- Osobny job/kontener LLM, streaming, embeddingi.
- Precyzyjne metering kosztów (MVP: prosty tygodniowy cap + log).

## 9. Open
- Brak — provider (free→paid gated), zakres (gap-fill inline), confidence (stałe 0.35), cache, prompt (wąski+grounding), judge (odłożony) ustalone.
