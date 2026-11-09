# Argus — Status projektu

**Ostatnia aktualizacja:** 2026-06-04
**Branch:** `feat/argus-phase1`
**Co to jest:** agent śledzenia trendów krypto+akcje z **samonauką wiarygodności źródeł** — źródło robi falsyfikowalne twierdzenie kierunkowe (claim), po horyzoncie mierzymy je względem ceny (prawda gruntowa), i aktualizujemy wiarygodność źródła. Ranking źródeł po **trafności**, nie po PnL/popularności.

## Gdzie chodzi
- **Oracle VPS** `84.235.174.129` (x86_64, 4 vCPU, 15GB, Ubuntu 22.04). 24/7, Docker Compose (`db` Postgres + `app`).
- **Dostęp do dashboardu (port zamknięty na firewallu):** tunel SSH
  `ssh -i "C:\ai\ssh-key-2026-05-19.key" -L 8090:localhost:8080 ubuntu@84.235.174.129` → http://localhost:8090 (horyzont na **1h**, bo 24h/7d/30d dojrzewają wolniej).
- **Deploy:** `scp -r argus ubuntu@VPS:~/ && ssh ... "cd ~/argus && docker compose up -d --build"`.
- **Testy (brak python na hoście Windows):** w Dockerze —
  `docker run --rm -v "<repo>/argus:/app" -w /app -v argus-pipcache:/root/.cache/pip -e PYTHONPATH=/app python:3.12-slim sh -c "pip install -q --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt && python -m pytest -q"` (98 testów).

## Architektura (pipeline)
```
Collectors → Claim Extractor → Storage(Postgres) → Analytics → UI
- collectors/rss.py        (RSS: krypto + reddit + news)        rule-v2 extractor + sector_map
- collectors/hyperliquid.py (pozycje traderów = claimy)         + Whale Consensus
                            ↓ claims (+ claim_audit)
Outcome Evaluator (1h/24h/7d/30d vs cena) → Source Scorer (Bayesian, decay, per źródło+aktywo)
FastAPI (/api/assets,/sources,/candles,/asset/{sym},/wallets*) + statyczny dashboard (Lightweight Charts)
APScheduler: rss 30min · hyperliquid 15min · evaluate 60min · score 6h
```
Ceny: krypto Binance, akcje yfinance. DB: local Postgres (Neon = jednolinijkowy switch).

## Zrobione (incrementy)
- **Faza 1** — pełny cykl claim→outcome→score→ranking na RSS. Tabele: assets, sources, items, claims, claim_audit, prices, outcomes, source_asset_scores, source_scores, wallet_positions.
- **Increment 2 — Dashboard v2** — overview (wszystkie scorable aktywa, klikalne) + drill-down ze świecami i markerami claimów; fix horyzontu + empty-state; akcje widoczne.
- **Increment 3 — Portfele Hyperliquid** — `Source(kind=hyperliquid)`, collector diffuje pozycje→position-claimy (open/flip), wszystkie pozycje w `wallet_positions` (off-watchlist widoczne, nie scorowane). confidence=position_value/equity. Whale Consensus (`kind=derived`). 30d horizon. Endpointy `/api/wallets*` + sekcja portfeli z preview. Frontend: dodawanie adresów.
- **Increment 4 — Reddit + stock-news + asocjacja sektorowa** — ekstraktor `rule-v2` (slang WSB, cashtagi). 6 subredditów (`kind=reddit`) + 5 portali (`kind=news`). `sectors.yaml` (alias→ticker, conf 0.3) → sygnał sektorowy trafia na akcje (NTR/NFE/DLNG z newsów). source_type=Source.kind.
- **Increment 5 — Likwidacje (market-context)** — osobny kontener `liq-listener` (reuse obrazu app) → Binance `!forceOrder@arr` WS (reconnect+circuit breaker) → tabela `liquidations` (tylko watchlist). `parse_force_order` (SELL=long_liq, BUY=short_liq). Endpointy `/api/liquidations?window=` + `/largest`. Panel (czerwony long-liq / zielony short-liq). Prune >30d. **NIE wpływa na scoring** (kontekst).
- **Increment 6 — LLM topic→ticker (gap-fill) + monitoring** — `llm/` router (Gemini free→OpenRouter free→paid gated) + extractor (wąski prompt+grounding gate, stałe conf 0.35) + cache (text_hash). Gap-fill inline w collect_rss (gdy rule-v2=0). **Monitoring:** `llm_calls` + `/api/llm/usage` + panel (koszt/użycie per provider/model, też free). Judge ODŁOŻONY. Klucze w `~/argus/.env` na VPS. Global per-job LLM cap (`LlmBudget`).
- **Increment 7 — HyperStats leaderboard auto-discovery** — kolektor `collectors/hyperstats.py`: darmowe backdoor JSON `v2-api.hyperstats.org/api/traders` → filtr jakości → insert-only top-N top-traderów HL jako śledzone portfele (`HL <grade> <addr8>`). Dzienny job; reużywa Inc-3 (pozycje→claimy) + `/api/wallets`. Wypełnia lukę „brak leaderboard API" z Inc 3. Bez przeglądarki.

## Stan na żywo (2026-06-05, po przebiegach)
- Sources: 4 rss + 6 reddit + 5 news + **~22 hyperliquid (2 ręczne + 20 auto z HyperStats S+)** + 1 derived. Kontenery: db + app + **liq-listener** (WS Binance, 14 symboli).
- Likwidacje: tabela `liquidations` + endpointy live; rośnie podczas zmienności rynku.
- **LLM:** gap-fill + monitoring live i DZIAŁA. Fix: domyślny model `gemini-flash-latest` (bo `gemini-2.0-flash` ma free quota=0); modele env-configurable (`ARGUS_GEMINI_MODEL`/`ARGUS_OR_FREE_MODEL`). `/api/llm/usage` pokazał gemini-flash-latest 9 ok / 4690 tok / $0. Claimy method=llm tylko dla itemów z jasnym powiązaniem (grounding gate zwraca [] dla słabych = poprawne). ✅ Global per-job cap wdrożony (`LlmBudget`, `ARGUS_LLM_MAX_PER_RUN=20` na cały przebieg) — ~11 wywołań/job vs ~450 wcześniej, 429-storm zniknął.
- Items ~545 (rss 261, reddit 150, news 134), claims ~45+ (rule + position).
- Outcomes: 1h rozliczone; 24h/7d/30d dojrzewają.
- Watchlista: 14 krypto (BTC,ETH,XRP,DOT,JUP,HBAR,RENDER,AERO,XAI,ONDO,AEVO,GROK,ALU,RUNE) + 7 akcji (XOMA,BYND,DLNG,LCID,NFE,NTR,PLG) + indeksy/makro (scorable=false).

## Roadmapa
- ⏭️ **Browser-human dla X/Twitter KOL:** Hermes MA już realny Chrome przez CDP (`browser-mcp` steruje chrome-hermes, `chrome-readonly-mcp` czyta żywe karty) — to darmowa ścieżka do X (brak API, login+CF). Hermes(laptop) wyciąga → POST do nowego endpointu ingest Argusa (VPS). Wymaga laptopa+sesji X. Osobny increment.
- ⏭️ **LLM judge** — gdy `method=llm` uzbiera realne metryki (teraz mało przez grounding gate + throttling). Realny sędzia = outcome-scoring.
- 🔧 **LLM operacyjnie:** gemini-flash-latest działa; ew. odblokować więcej darmowych kwot lub `ARGUS_LLM_ALLOW_PAID=true` + kredyt.

## Znane fakty / pułapki
- Sieć laptopa ma korporacyjny MITM proxy → pip/feedy w kontenerze wymagają `--trusted-host pypi.org --trusted-host files.pythonhosted.org`; feedy SSL-fail lokalnie. VPS czysty. Testy zawsze w Dockerze.
- Hyperliquid: brak API leaderboard (adresy ręcznie / z trackerów). AEVO/GROK/ALU nie ma na HL.
- GROK=grok-2 / GROKUSDT niepewne na Binance (collector przeżyje dzięki try/except).
- Reddit `.rss` działa z feedparser (UA nie blokowany); Reddit JSON 403 z VPS.
- Pełna dokumentacja: `docs/superpowers/specs/2026-06-0*-argus-*` + `docs/superpowers/plans/2026-06-0*-argus-*`; pamięć: `project_argus`, `reference_oracle_vps`.
