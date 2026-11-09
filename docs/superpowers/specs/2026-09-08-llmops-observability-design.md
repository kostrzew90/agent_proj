# LLMOps — centralna obserwowalność wywołań LLM (Etap 1)

Data: 2026-09-08
Status: design zaakceptowany, gotowy do planu implementacji
Zakres: Etap 1 — koszty i zdrowie. Jakość (Etap 2) i deep-trace (Etap 3) mają własne specy.

## Problem

Siedem projektów woła API LLM u pięciu dostawców. Nie ma miejsca, w którym widać całość:
ile kosztuje miesiąc, który model zjada budżet, który projekt się wywala.

Gorzej — wzorzec „tabela z kosztami" powstał już **cztery razy niezależnie**, w czterech bazach,
z czterema różnymi cennikami:

| Implementacja | Tabela | Cennik dla nieznanego modelu |
|---|---|---|
| `RAG/backend/core/database.py:204` | `llm_calls` (baza RAG) | brak wyceny |
| `argus/argus/models.py:149` | `llm_calls` (baza Argus) | **$0.00** — zaniża |
| `mcp-servers/llm-proxy/server.py:169` | `hermes_llm_costs` | **$3/$15 za 1M** placeholder — zawyża |
| `kontekst ai/ai_repo/core/llm.py:87` | przez `record_llm_call` | brak wyceny |

Dwa systemy kłamią w przeciwne strony, dwa nie liczą wcale. Żadna z dzisiejszych liczb
kosztowych nie nadaje się do podjęcia decyzji.

Dwa z nich (`llm-proxy`, `kontekst-ai`) dodatkowo **zgadują tokeny** jako `len(tekst) // 4`,
zamiast brać je z odpowiedzi dostawcy — i nigdzie nie zapisują, że to szacunek.

Dodatkowo: **żaden dostawca nie zwraca kosztu** — potwierdzone w `RAG/backend/core/openrouter.py:172`
(tylko `prompt_tokens`/`completion_tokens`) i `RAG/backend/core/llm.py:71`. Koszt zawsze jest
wyliczany u nas, więc poprawność cennika jest jedynym źródłem poprawności kosztów.

## Cel

Jedno źródło prawdy o wywołaniach LLM w całej infrastrukturze i jeden dashboard, który
odpowiada na: ile wydaliśmy, na co, gdzie się psuje.

Kryteria sukcesu Etapu 1:

1. Każde wywołanie LLM z 7 projektów tworzy wiersz w `llmops.llm_calls`.
2. Koszt liczony z jednego, wersjonowanego cennika — zmiana ceny przelicza historię.
3. Dashboard w Grafanie pokazuje koszt/tokeny/wywołania/error rate: dziś, w czasie, wg projektu, dostawcy, modelu.
4. Awaria telemetrii nigdy nie wywraca wywołania LLM.

## Zasada architektoniczna

```
llm_calls  = centralna metryka WSZYSTKICH wywołań LLM
Langfuse   = szczegółowy trace/debug tam, gdzie ma to sens (Etap 3)
Grafana    = centralny cockpit całej infrastruktury AI
```

## Architektura

```
RAG ───────────┐
Argus ─────────┤
llm-proxy ─────┤   fire-and-forget      ┌───────────┐      ┌────────────┐
Hermes ────────┼── POST /v1/calls ────► │  kolektor │ ───► │ llmops DB  │
Selfmadeagent ─┤   (JSON, non-blocking) │ (FastAPI) │      │ (Postgres) │
kontekst-ai ───┤                        └───────────┘      └─────┬──────┘
trading-app ───┘                                                 │
                                                                 ▼
                                                    argus-grafana (istniejąca)
```

Nowy stack `llmops/` na Contabo VPS: Postgres + kolektor. **Osobny od `argus-pg` i `rag-postgres`** —
telemetria wszystkich siedmiu projektów nie może umierać razem z restartem jednego z nich.

Grafana **nie jest przenoszona**. Zostaje w stacku Argusa (`argus/docker-compose.yml:29`, port 3000
na Tailscale), gdzie działa i obsługuje pool-monitor. Dokładamy jej tylko provisioned datasource
i dashboard z plików trzymanych w `llmops/grafana/`.

## Model danych

### `llm_calls`

```sql
CREATE TABLE llm_calls (
    id           BIGSERIAL PRIMARY KEY,
    ts           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    project      TEXT         NOT NULL,   -- rag, argus, hermes, selfmadeagent, kontekst-ai, trading-app, llm-proxy
    service      TEXT         NOT NULL,   -- chat-api, worker, guardian, bridge, orchestrator
    environment  TEXT         NOT NULL,   -- production, dev
    host         TEXT         NOT NULL,   -- contabo-vps, local-win, mac-studio
    provider     TEXT         NOT NULL,   -- openrouter, gemini, groq, ollama, anthropic
    model        TEXT         NOT NULL,
    call_type    TEXT         NOT NULL,   -- generate, embed, rerank, judge, rewrite, diagnose
    tokens_in    INTEGER      NOT NULL DEFAULT 0,
    tokens_out   INTEGER      NOT NULL DEFAULT 0,
    tokens_estimated BOOLEAN  NOT NULL DEFAULT FALSE,  -- TRUE = zgadywane z dlugosci tekstu
    cost_usd     NUMERIC(12,6),           -- NULL = wylicz z cennika
    latency_ms   INTEGER,
    ok           BOOLEAN      NOT NULL,
    error        TEXT,                    -- skrócony do 300 znaków, po redakcji kluczy API
    trace_id     TEXT                     -- Langfuse trace, wypełniane od Etapu 3
);

CREATE INDEX idx_llm_calls_ts         ON llm_calls (ts DESC);
CREATE INDEX idx_llm_calls_project_ts ON llm_calls (project, ts DESC);
CREATE INDEX idx_llm_calls_model_ts   ON llm_calls (model, ts DESC);
```

Hierarchia `project/service/environment/host` jest w schemacie **od początku**. Dołożenie wymiaru
później oznacza backfill historii, której nikt nie zbackfilluje.

`tokens_estimated` z tego samego powodu: bez tej flagi tokeny zgadnięte przez llm-proxy
i kontekst-ai wpadają do sumy kosztów nieodróżnialne od zmierzonych. To ta sama klasa
problemu, co `NULL` vs `0` przy brakującym cenniku — dashboard musi umieć powiedzieć,
czego nie wie.

### `model_pricing`

```sql
CREATE TABLE model_pricing (
    id               SERIAL PRIMARY KEY,
    provider         TEXT NOT NULL,
    model            TEXT NOT NULL,
    usd_per_mtok_in  NUMERIC(10,4) NOT NULL,
    usd_per_mtok_out NUMERIC(10,4) NOT NULL,
    valid_from       TIMESTAMPTZ   NOT NULL,
    UNIQUE (provider, model, valid_from)
);
```

### `v_llm_calls_costed`

Widok zwracający `llm_calls` z kolumną `effective_cost_usd`:

```
COALESCE(
    cost_usd,                                   -- koszt podany przez klienta, jeśli był
    tokens_in  / 1e6 * cennik.usd_per_mtok_in
  + tokens_out / 1e6 * cennik.usd_per_mtok_out  -- cennik obowiązujący w momencie ts
)
```

Cennik dobierany po `(provider, model)` z najpóźniejszym `valid_from <= ts`. Brak wpisu
w cenniku → `effective_cost_usd` jest `NULL`, **nie zero**. To celowe: „nie wiem, ile to
kosztowało" musi być odróżnialne od „to było darmowe", bo dokładnie to rozróżnienie
zgubiły trzy istniejące implementacje. Dashboard pokazuje osobny licznik wywołań bez cennika.

Wszystkie panele Grafany czytają z widoku, nigdy z surowej tabeli.

Retencja: 90 dni surowych wierszy, kasowane cronem. Bez rollupów — przy 50k wywołań dziennie
to ~4,5 mln wierszy, czego Postgres nie zauważy. Rollupy dokładamy, gdy zapytania faktycznie
zwolnią.

## Kolektor

FastAPI, jeden endpoint:

```
POST /v1/calls
Content-Type: application/json
Authorization: Bearer <LLMOPS_TOKEN>

{ project, service, environment, host, provider, model, call_type,
  tokens_in, tokens_out, latency_ms, ok, error?, cost_usd?, trace_id? }

→ 202 Accepted  (bez ciała)
```

- Waliduje kształt, obcina `error` do 300 znaków, redaguje z niego klucze API.
- Odrzuca ładunki z polami `prompt`/`response`/`input`/`output` — treści tu nie trzymamy (to Etap 3, Langfuse).
- Batch (`POST /v1/calls/batch`, lista do 100) dla wolumenowych producentów jak Argus.
- Poza tym `GET /health`.

Uwierzytelnianie: statyczny bearer token z env. Usługa nasłuchuje wyłącznie na sieci
dockerowej i Tailscale IP, nigdy publicznie — zgodnie z regułą hosta (Docker omija ufw,
więc porty bindujemy do konkretnego IP, nie `0.0.0.0`).

## Klient

Jeden mały moduł `llmops_client` (~70 linii), kanoniczne źródło w `llmops/client/`,
wendorowany do projektów skryptem synchronizującym.

```python
llmops_client.record(
    provider="openrouter", model="anthropic/claude-sonnet-4.5",
    call_type="generate", tokens_in=1200, tokens_out=340,
    latency_ms=2100, ok=True,
)
```

- `project/service/environment/host` czytane raz z env (`LLMOPS_PROJECT`, `LLMOPS_SERVICE`,
  `LLMOPS_ENV`, `LLMOPS_HOST`) — nie są argumentami wywołania, więc nie da się ich zapomnieć.
- **Fire-and-forget**: wysyłka w tle, krótki timeout (2 s), całość w `try/except`.
  Wariant async dla FastAPI/asyncio, sync dla reszty.
- Brak `LLMOPS_URL` → no-op. Ten sam wzorzec, co `RAG/backend/core/langfuse_client.py`.
- **Nigdy nie podnosi wyjątku do wołającego.** Niedostępny kolektor = warning w logu
  i utracona metryka. Telemetria nie jest transakcją.

## Punkty wpięcia

Siedem projektów, w każdym jedno lub kilka wąskich gardeł, przez które i tak wszystko przechodzi:

| Projekt | Plik | Uwaga |
|---|---|---|
| Argus | `argus/argus/llm/router.py:120` (`_record`) | gotowy hook — dopisujemy wywołanie obok istniejącego zapisu |
| llm-proxy | `mcp-servers/llm-proxy/server.py:54` (`_record_cost`) | gotowy hook, jw. |
| Hermes | — | woła llm-proxy (`bridge/hermes_bridge.py:433`), **pokryty pośrednio** |
| RAG | `services/chat_service.py:465` (pętla `call_records`) | **jeden hook** pokrywa rewrite/embed/generate/judge |
| RAG (workery) | `core/embeddings.py` | ścieżka ingestu z pominięciem chat_service |
| kontekst ai | `ai_repo/core/llm.py:87` (`_record`) | gotowy hook — czwarta istniejąca implementacja |
| Selfmadeagent | `orchestrator/agent/providers.py:68` (`call_llm`) | LiteLLM, usage z odpowiedzi |
| trading-app | `core/ollama_client.py:113/147/186` | zero telemetrii dzisiaj |

**Cztery z siedmiu projektów mają już właściwy hook** (Argus `_record`, llm-proxy `_record_cost`,
kontekst-ai `_record`, RAG pętla `call_records`) — tam to dopisanie kilku linii. Nowy punkt
wpięcia trzeba stworzyć tylko w Selfmadeagencie i trading-appie.

**Nic nie jest usuwane w Etapie 1.** Trzy istniejące tabele zostają, projekty piszą podwójnie.
RAG-owy `llm_calls` obsługuje realną funkcję produktu (panel „N wywołań · koszt" w
`RAG/frontend/src/pages/Chat.tsx:140`) i wisi na `message_id` — zostaje niezależnie od Etapu 1.
Wygaszanie pozostałych rozważymy, gdy centralna udowodni, że działa.

## Dashboard

`llmops/grafana/dashboards/llm-observability.json`, provisioned z pliku.

```
┌──────────────┬──────────────┬──────────────┬─────────────┐
│ COST TODAY   │ TOKENS TODAY │ LLM CALLS    │ ERROR RATE  │
├──────────────┴──────────────┴──────────────┴─────────────┤
│ COST / DAY (30 dni)                                      │
├────────────────────────────┬─────────────────────────────┤
│ COST BY PROJECT            │ COST BY PROVIDER            │
├────────────────────────────┼─────────────────────────────┤
│ CALLS BY MODEL             │ ERROR RATE BY PROJECT       │
└────────────────────────────┴─────────────────────────────┘
```

Plus mały panel „wywołania bez wpisu w cenniku" — bez niego nieznany model po cichu wypada
z sumy kosztów, czyli wracamy do dzisiejszego problemu.

Wpięcie do istniejącej Grafany: dwa dodatkowe bind-mounty w `argus/docker-compose.yml`
(datasource + katalog dashboardów). Zmiana dwuliniowa, bez ruszania pool-monitora.

## Kolejność wdrożenia

Każdy krok ma własne kryterium weryfikacji:

1. **Stack `llmops`** (Postgres + schemat + cennik startowy) → ręczny `INSERT`, widok liczy koszt poprawnie; model spoza cennika daje `NULL`, nie `0`.
2. **Kolektor + klient** → test integracyjny: wiersz ląduje w bazie. Kolektor ubity → wywołanie LLM dalej działa, w logu warning.
3. **Argus + llm-proxy** (gotowe hooki) → po godzinie ruchu sumy zgadzają się z ich lokalnymi tabelami.
4. **RAG** (3 pliki) → panel w `Chat.tsx` nadal działa, centralna tabela ma te same wywołania.
5. **Selfmadeagent, kontekst ai, trading-app** → każdy widoczny w podziale „cost by project".
6. **Dashboard** → kafle zgadzają się z ręcznym SQL-em na tym samym oknie czasu.
7. **Backfill** (opcjonalnie) → historia z trzech istniejących tabel, przeliczona nowym cennikiem.

## Poza zakresem Etapu 1

Świadomie odłożone, każde do własnego specu:

- **Jakość** (Etap 2): `quality_score`, judge score, feedback użytkownika, groundedness. Dziś sygnał jakości ma tylko RAG.
- **Deep-trace** (Etap 3): wypełnianie `trace_id` i przejście z wiersza Grafany do trace'u w Langfuse.
- Alerty i budżety kosztowe per projekt (llm-proxy ma już własny tygodniowy budżet — na razie zostaje u siebie).
- Wygaszanie trzech istniejących tabel kosztowych.
- Rollupy i agregaty.
- Routing modeli na podstawie ceny/jakości.

## Ryzyka i założenia

- **Założenie do zweryfikowania:** `trading-app` i `kontekst ai` nie mają `docker-compose.yml` w repo, więc ich obecność na Contabo VPS potwierdzam dopiero na żywym hoście. Klient działa tak samo lokalnie, więc to nie blokuje projektu — może zmienić tylko wartość `host` i adres kolektora.
- **Drift wendorowanego klienta:** siedem kopii może się rozjechać. Mitygacja: kanoniczne źródło w `llmops/client/` plus skrypt synchronizujący; test w CI porównujący sumy kontrolne.
- **Kompletność cennika** decyduje o poprawności wszystkich liczb kosztowych. Mitygacja: panel „wywołania bez wpisu w cenniku" czyni lukę widoczną, zamiast po cichu ją zerować.
- **Utrata telemetrii przy awarii kolektora** — zaakceptowana. Alternatywa (kolejka na dysku, retry) to złożoność nieproporcjonalna do wartości metryki.
