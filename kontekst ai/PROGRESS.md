# AI-Aware Repo — Progress Tracker

**Ostatnia aktualizacja**: 2026-03-04

## Status faz

| Faza | Status | Opis |
|------|--------|------|
| FAZA 1 | ✅ DONE | Infrastruktura (Docker, DB, Config, Makefile) |
| FAZA 2 | ✅ DONE | Core — Indexer, Parsery, Graph Builder |
| FAZA 3 | ✅ DONE | Embeddingi, LLM, Retrieval, Re-ranker, Prompt Composer |
| FAZA 4 | ✅ DONE | Project Memory + Auto-bootstrap |
| FAZA 5 | ✅ DONE | API (FastAPI) + CLI (Typer) |
| FAZA 6 | ✅ DONE | MCP Server |
| FAZA 7 | ✅ DONE | Plugin System (szkielet) |
| FAZA 8 | ✅ DONE | Testy |
| FAZA 9A | ✅ DONE | Backend instrumentacja + metryki |
| FAZA 9B | ⚠️ KOD GOTOWY | Chainlit chat + force-graph (wymaga Ollama lub Anthropic API key) |
| FAZA 9C | ✅ DONE | Dashboard monitoringu |

## FAZA 9 — Web Frontend + Monitoring

### Podzial na podfazy

| Podfaza | Opis | Zalezy od |
|---------|------|-----------|
| **9A** | Backend: instrumentacja (metryki do DB) | — |
| **9B** | Frontend: Chainlit chat + force-graph | 9A |
| **9C** | Frontend: Dashboard monitoringu | 9A |

---

### FAZA 9A — Backend: Instrumentacja i metryki ✅ DONE

**Cel**: Wypelnic istniejace tabele (`log_events`, `retrieval_logs`) danymi + dodac nowe metryki.

**Zrobione**:
- `migrations/004_monitoring.sql` — nowe tabele `indexing_jobs` + `llm_calls`, ALTER `retrieval_logs` (+4 kolumny)
- `ai_repo/core/database.py` — modele ORM: `IndexingJob`, `LLMCall`, rozszerzony `RetrievalLog`
- `ai_repo/core/metrics.py` — helpery: `emit_event()`, `record_llm_call()`, `start_indexing_job()`, `finish_indexing_job()`
- `ai_repo/core/indexer.py` — job tracking (start/finish) + per-file error events
- `ai_repo/core/embeddings.py` — opcjonalny `db` param, error events na timeout/failure
- `ai_repo/core/llm.py` — opcjonalny `db`+`purpose`, LLM call recording, fallback events
- `ai_repo/plugins/loader.py` — plugin load/fail events do `log_events`
- `ai_repo/core/retriever.py` — rozszerzony `_log_retrieval()` (semantic/keyword/final count, embedding_ms), fix: `provider_used="semantic+keyword"`
- `ai_repo/api/routes/monitoring.py` — 5 endpointow: retrieval-stats, llm-stats, indexing-history, errors, overview
- `ai_repo/api/server.py` — monitoring router zarejestrowany
- `ai_repo/api/routes/query.py` — LLMClient dostaje `db` i `purpose`

#### Obecny stan monitoringu:

| Zrodlo | Persisted? | Luki |
|--------|:---:|------|
| Retrieval latency (retriever.py → `retrieval_logs`) | ✅ | Brak semantic/keyword breakdown, `context_tokens` puste |
| System stats (/stats) | ✅ real-time | Tylko countery |
| Health (/health) | ✅ real-time | Brak historii |
| `log_events` tabela | ⚠️ SCHEMA JEST | **Nikt nie pisze do tej tabeli!** |
| Indexing stats (indexer.py) | ❌ logger only | Brak timing, brak DB |
| Embedding metrics (embeddings.py) | ❌ logger only | Brak latency/batch |
| LLM metrics (llm.py) | ❌ logger only | Brak latency/tokenow/kosztow |
| Plugin status (loader.py) | ❌ logger only | Brak per-plugin tracking |

#### Co zrobic:

1. **Wypelnic `log_events`** — dodac helper `emit_event(service, level, message, signature, meta)` w database.py
   - Wywolywac z: indexer (start/end/error), embeddings (timeout/error), llm (error/fallback), plugins (load/fail)

2. **Rozszerzyc `retrieval_logs`**:
   - Dodac kolumny: `semantic_count INT`, `keyword_count INT`, `final_count INT`, `embedding_ms REAL`
   - Wypelnic `context_tokens` (juz istnieje ale puste)
   - Migracja: `migrations/004_monitoring.sql`

3. **Nowa tabela `indexing_jobs`**:
   ```sql
   CREATE TABLE indexing_jobs (
       id SERIAL PRIMARY KEY,
       repo_id TEXT NOT NULL,
       started_at TIMESTAMPTZ DEFAULT NOW(),
       finished_at TIMESTAMPTZ,
       files_scanned INT DEFAULT 0,
       files_indexed INT DEFAULT 0,
       files_skipped INT DEFAULT 0,
       files_errored INT DEFAULT 0,
       chunks_created INT DEFAULT 0,
       symbols_found INT DEFAULT 0,
       duration_ms REAL,
       status TEXT DEFAULT 'running'  -- running, completed, failed
   );
   ```

4. **Nowa tabela `llm_calls`**:
   ```sql
   CREATE TABLE llm_calls (
       id SERIAL PRIMARY KEY,
       ts TIMESTAMPTZ DEFAULT NOW(),
       provider TEXT NOT NULL,        -- ollama, anthropic
       model TEXT,
       purpose TEXT,                  -- query, bootstrap, explain
       input_tokens INT,
       output_tokens INT,
       latency_ms REAL,
       success BOOLEAN DEFAULT true,
       error_message TEXT
   );
   CREATE INDEX idx_llm_calls_ts ON llm_calls(ts);
   ```

5. **Instrumentacja modulow**:
   - `embeddings.py`: mierzyc latency per batch, logowac do `log_events`
   - `llm.py`: mierzyc latency + tokeny, zapisywac do `llm_calls`
   - `indexer.py`: zapisywac job do `indexing_jobs` (start/end/stats)
   - `loader.py`: emit plugin load/fail events do `log_events`

6. **Nowe API endpointy** (routes/monitoring.py):
   - `GET /monitoring/retrieval-stats` — avg latency, query count, provider distribution (z `retrieval_logs`)
   - `GET /monitoring/llm-stats` — provider usage, avg latency, token totals (z `llm_calls`)
   - `GET /monitoring/indexing-history` — ostatnie joby indexowania (z `indexing_jobs`)
   - `GET /monitoring/errors` — top error signatures, recent errors (z `log_events`)
   - `GET /monitoring/health-history` — snapshot stanu systemu (periodic health check → DB)
   - `GET /monitoring/overview` — agregat: health + stats + last errors + last indexing

#### Nowe pliki:
```
ai_repo/
├── core/
│   └── metrics.py               # emit_event(), record_llm_call(), record_indexing_job()
├── api/routes/
│   └── monitoring.py            # GET /monitoring/* endpointy
migrations/
└── 004_monitoring.sql           # indexing_jobs, llm_calls, ALTER retrieval_logs
```

---

### FAZA 9B — Frontend: Chainlit Chat + Force-Graph ⚠️ KOD GOTOWY

**Status**: Kod zaimplementowany, UI sie laduje, ale wymaga dzialajacego LLM (Ollama lub Anthropic API key).

**Zrobione**:
- `chainlit_app.py` — Chainlit handlers: `@cl.on_chat_start` (welcome + sidebar z memory facts), `@cl.on_message` (RAG pipeline: retrieve → compose → stream → sources + mini-graph link)
- `.chainlit/config.toml` — Chainlit config (wygenerowany przez chainlit 2.9.6)
- `static/graph.html` — standalone force-graph page (CDN force-graph by vasturiano), klikalne węzły, expand neighbors via `/graph/neighbors/{name}`, color-coded nodes wg kind
- `ai_repo/api/server.py` — mount_chainlit() at `/chat`, StaticFiles at `/static`
- `requirements.txt` — dodane `chainlit>=2.0.0`

**Weryfikacja**:
- ✅ `http://localhost:8100/chat/` — Chainlit UI sie laduje (200)
- ✅ `http://localhost:8100/static/graph.html` — force-graph page (200)
- ❌ Chat nie odpowiada — brak LLM (Ollama nie uruchomiona, brak ANTHROPIC_API_KEY)

**Aby dzialalo — potrzeba jednego z**:
1. Uruchomić Ollama: `ollama serve` + `ollama pull qwen3:8b`
2. Ustawic Anthropic: stworzyc `kontekst ai/.env` z `ANTHROPIC_API_KEY=sk-ant-...` i `LLM_PROVIDER=anthropic`

#### Architektura:
- `mount_chainlit(app, target="chainlit_app.py", path="/chat")` w `server.py`
- force-graph z CDN: `//cdn.jsdelivr.net/npm/force-graph`
- Streaming: `async for token in llm.generate_stream(...)` → `await msg.stream_token(token)`
- Graf data: `{nodes: [{id, name, kind, ...}], links: [{source, target, edge_type}]}`
- Sources: `cl.Text` elements z `display="side"` (score + preview)
- Sidebar: `cl.ElementSidebar` z project memory facts (top 20)

---

### FAZA 9C — Frontend: Dashboard Monitoringu ✅ DONE

**Status**: Zaimplementowany jako standalone `static/dashboard.html`.

**Zrobione**:
- `static/dashboard.html` — standalone HTML z embedded CSS + JS (zero zależności)
- Dark theme spójny z `graph.html` (#0d1117 / #161b22 / #30363d)
- CSS Grid 2 kolumny, 4 rzędy (responsywny → 1 kolumna na mobile)
- 7 kart: System Health, Index Stats, Retrieval Performance, LLM Usage, Last Indexing Job, Top Errors 24h, Recent Errors
- 3 parallel fetche: `/monitoring/overview` + `/health` + `/stats`
- Auto-refresh co 30s z "Last updated" timestamp
- Expandable Recent Errors (5 vs 20 wierszy)
- Graceful degradation: "API unavailable" per karta jeśli fetch padnie
- HTML escaping (XSS protection)

**Weryfikacja**: `http://localhost:8100/static/dashboard.html`

#### Layout dashboardu:

```
┌─────────────────────────────────────────────────────────────┐
│  SYSTEM HEALTH                    INDEX STATS               │
│  ┌──────┐ ┌──────┐ ┌──────┐     Docs: 142  Chunks: 1,847  │
│  │ DB   │ │Ollama│ │Embed │     Symbols: 523  Edges: 1,291 │
│  │  ✅  │ │  ✅  │ │  ✅  │     Embedding coverage: 98.2%  │
│  └──────┘ └──────┘ └──────┘                                 │
├─────────────────────────────────────────────────────────────┤
│  RETRIEVAL PERFORMANCE            LLM USAGE                 │
│  ┌─────────────────────────┐     Provider: ollama (94%)     │
│  │  avg: 142ms  p95: 380ms│     Avg latency: 1.2s          │
│  │  ▁▂▃▅▇█▇▅▃▂▁▂▃▅▇      │     Tokens today: 48,291      │
│  │  queries/h: 23         │     Fallbacks: 2 (anthropic)   │
│  └─────────────────────────┘                                │
├─────────────────────────────────────────────────────────────┤
│  LAST INDEXING JOB                TOP ERRORS (24h)          │
│  Status: completed ✅             TimeoutError (embed): 12  │
│  Duration: 4.2s                   ConnectionErr (ollama): 3 │
│  Files: 142 indexed, 0 errors     ParseError (sql): 1      │
│  Chunks: 1,847  Symbols: 523                                │
├─────────────────────────────────────────────────────────────┤
│  PLUGIN STATUS                    MEMORY FACTS              │
│  plugin-logs: ✅ loaded           Total: 18 facts           │
│  plugin-template: ✅ loaded       Auto-bootstrap: 15        │
│  custom-plugin: ❌ failed         Manual: 3                 │
│                                   Avg confidence: 0.82      │
└─────────────────────────────────────────────────────────────┘
```

#### Implementacja:
- Chainlit custom page `/dashboard` lub osobna zakladka w sidebar
- Dane z `GET /monitoring/overview` (jeden call, agreguje wszystko)
- Auto-refresh co 30s (lub SSE/WebSocket jesli Chainlit wspiera)
- Klikalne sekcje: np. klik na "TOP ERRORS" → rozwija liste z timestamps

#### Widoki szczegolowe (drill-down):
1. **Retrieval** — tabela ostatnich queries z latency, wynikami, providerem
2. **LLM** — timeline callek z tokenami, latency, fallbackami
3. **Indexing** — historia jobow, per-file errors
4. **Errors** — full log_events browser z filtrami (service, level, time range)

### Nowe zaleznosci (cala faza 9):
```
chainlit>=2.0.0
```

### Referencje:
- react-force-graph / force-graph (vasturiano) — ~3-5K stars, MIT
- Chainlit — ~11.5K stars, Apache 2.0, custom elements via JSX
- Chainlit + FastAPI: `mount_chainlit()` utility
- Chainlit ElementSidebar: `cl.ElementSidebar.set_elements()`
- Chainlit streaming: `msg.stream_token()` + `msg.update()`

## Szczegoly — co jest zrobione

### FAZA 1 ✅
- `docker-compose.ai-repo.yml` — Postgres 16 + pgvector na porcie 5435
- `migrations/001_init.sql` — documents, chunks + HNSW + GIN indexes
- `migrations/002_graph.sql` — symbols, edges
- `migrations/003_memory.sql` — project_memory, retrieval_logs, log_events
- `.env.example` — wszystkie zmienne
- `config.yaml` — pelna konfiguracja
- `Makefile` — targety: ai-up, ai-down, ai-migrate, ai-index, ai-api, ai-query, ai-graph
- `requirements.txt` — zaleznosci Python
- `ai_repo/config.py` — Pydantic settings ladujacy .env + config.yaml
- Wszystkie `__init__.py` dla pakietow

### FAZA 2 ✅
- `ai_repo/core/database.py` — ORM modele (Document, Chunk, Symbol, Edge, ProjectMemory, RetrievalLog, LogEvent) + Database manager z CRUD + semantic/keyword search + graph neighbors/impact
- `ai_repo/core/indexer.py` — skaner repo, incremental (mtime+hash), .gitignore, pipeline scan→parse→chunk→upsert
- `ai_repo/core/chunker.py` — code-aware chunking (AST per klasa/funkcja dla Pythona, sliding window fallback)
- `ai_repo/core/graph_builder.py` — ParseResult → symbols + edges w DB
- `ai_repo/parsers/python_parser.py` — ast.NodeVisitor: klasy, funkcje, importy, wywolania, dziedziczenie
- `ai_repo/parsers/yaml_parser.py` — docker-compose services, depends_on, config keys
- `ai_repo/parsers/dockerfile_parser.py` — FROM, COPY, EXPOSE, ENTRYPOINT/CMD
- `ai_repo/parsers/sql_parser.py` — CREATE TABLE, REFERENCES, CREATE INDEX
- `ai_repo/parsers/generic_parser.py` — requirements.txt, .env, markdown, toml/cfg/ini

### FAZA 3 ✅
- `ai_repo/core/embeddings.py` — Ollama embedding client (async + sync, batch po 32)
- `ai_repo/core/llm.py` — Ollama primary + Anthropic fallback, streaming
- `ai_repo/core/retriever.py` — dual retrieval (semantic + keyword + graph expansion)
- `ai_repo/core/reranker.py` — RRF (k=60) z graph bonus
- `ai_repo/core/prompt_composer.py` — budowanie kontekstu z chunks + graph + memory + risk analysis

### FAZA 4 ✅
- `ai_repo/core/memory.py` — MemoryManager: CRUD (set/get/search/delete), auto-bootstrap z LLM

### FAZA 5 ✅
- `ai_repo/__main__.py` — entry point: `python -m ai_repo`
- `ai_repo/cli.py` — Typer CLI: index, query, graph, explain, serve, plugin install/list
- `ai_repo/api/server.py` — FastAPI factory z lifespan (DB init, plugin load)
- `ai_repo/api/routes/query.py` — POST /query (RAG pipeline)
- `ai_repo/api/routes/graph.py` — GET /graph/neighbors, /graph/impact
- `ai_repo/api/routes/memory.py` — GET/POST/DELETE /memory
- `ai_repo/api/routes/system.py` — GET /health, /stats

### FAZA 6 ✅
- `ai_repo/api/mcp/registry.py` — ToolRegistry (rejestracja + listowanie narzedzi MCP)
- `ai_repo/api/mcp/tools.py` — 5 core tools: repo.search, repo.graph_neighbors, repo.impact_analysis, repo.memory_get, repo.memory_set
- `ai_repo/api/mcp/server.py` — FastAPI router: GET /mcp/tools/list, POST /mcp/tools/call

### FAZA 7 ✅
- `ai_repo/plugins/base.py` — PluginBase (ABC) + PluginContext dataclass
- `ai_repo/plugins/loader.py` — PluginLoader: discover (skanuje plugin dirs) + load_all (importuje + rejestruje)
- `ai_repo/plugins/installer.py` — PluginInstaller: git clone → _vendor/<name>/<ref>/
- `ai_repo/plugins/sandbox.py` — PluginSandbox: allowlist + permissions check
- `plugins/examples/plugin-template/` — minimalny przyklad pluginu
- `plugin-logs/` — plugin z tools: logs.search, logs.error_summary

### FAZA 8 ✅
- `tests/conftest.py` — fixtures: mock_db, mock_llm, mock_embeddings, sample_retrieval_results
- `tests/test_parsers.py` — testy parserow: Python (6), YAML (3), SQL (3), Dockerfile (3), Generic (3)
- `tests/test_database.py` — testy DB operations (mock-based)
- `tests/test_retriever.py` — testy: reranker RRF (4), retriever pipeline (1), prompt_composer (5)

## Struktura katalogow (kompletna)

```
kontekst ai/
├── docker-compose.ai-repo.yml  ✅
├── config.yaml                  ✅
├── .env.example                 ✅
├── Makefile                     ✅
├── requirements.txt             ✅
├── PROGRESS.md                  ✅ (ten plik)
│
├── ai_repo/
│   ├── __init__.py              ✅
│   ├── config.py                ✅
│   ├── __main__.py              ✅
│   ├── cli.py                   ✅
│   │
│   ├── api/
│   │   ├── __init__.py          ✅
│   │   ├── server.py            ✅
│   │   ├── routes/
│   │   │   ├── __init__.py      ✅
│   │   │   ├── query.py         ✅
│   │   │   ├── graph.py         ✅
│   │   │   ├── memory.py        ✅
│   │   │   ├── monitoring.py    ✅ (9A)
│   │   │   └── system.py        ✅
│   │   └── mcp/
│   │       ├── __init__.py      ✅
│   │       ├── server.py        ✅
│   │       ├── tools.py         ✅
│   │       └── registry.py      ✅
│   │
│   ├── core/
│   │   ├── __init__.py          ✅
│   │   ├── database.py          ✅
│   │   ├── indexer.py           ✅
│   │   ├── chunker.py           ✅
│   │   ├── embeddings.py        ✅
│   │   ├── llm.py               ✅
│   │   ├── graph_builder.py     ✅
│   │   ├── retriever.py         ✅
│   │   ├── reranker.py          ✅
│   │   ├── memory.py            ✅
│   │   ├── metrics.py           ✅ (9A)
│   │   └── prompt_composer.py   ✅
│   │
│   ├── parsers/
│   │   ├── __init__.py          ✅
│   │   ├── python_parser.py     ✅
│   │   ├── yaml_parser.py       ✅
│   │   ├── dockerfile_parser.py ✅
│   │   ├── sql_parser.py        ✅
│   │   └── generic_parser.py    ✅
│   │
│   └── plugins/
│       ├── __init__.py          ✅
│       ├── base.py              ✅
│       ├── loader.py            ✅
│       ├── installer.py         ✅
│       └── sandbox.py           ✅
│
├── migrations/
│   ├── 001_init.sql             ✅
│   ├── 002_graph.sql            ✅
│   ├── 003_memory.sql           ✅
│   └── 004_monitoring.sql       ✅ (9A)
│
├── plugins/
│   └── examples/
│       └── plugin-template/     ✅
│           ├── plugin.yaml
│           └── __init__.py
│
├── chainlit_app.py              ✅ (9B)
├── .chainlit/
│   └── config.toml              ✅ (9B)
├── static/
│   ├── graph.html               ✅ (9B)
│   └── dashboard.html           ✅ (9C)
│
├── plugin-logs/                 ✅
│   ├── plugin.yaml
│   └── __init__.py
│
└── tests/                       ✅
    ├── conftest.py
    ├── test_parsers.py
    ├── test_database.py
    └── test_retriever.py
```

## Weryfikacja

```bash
# Indeksuj repo
python -m ai_repo index --repo-path .

# Zapytaj RAG
python -m ai_repo query "jakie tabele sa w projekcie?"

# Uruchom API
python -m ai_repo serve
# -> curl localhost:8100/health
# -> curl localhost:8100/stats
# -> curl localhost:8100/mcp/tools/list

# Testy
pytest tests/

# Graf symboli
python -m ai_repo graph Database --depth 2

# Wyjasnienie symbolu
python -m ai_repo explain Retriever
```
