# Plan: AI-Aware Repo — Pełna implementacja

## Context

Budujemy **samodzielne, czyste narzędzie developerskie** ("AI-aware repo") które:
- Indeksuje **dowolne** repo do Postgres (pgvector) z embeddingami
- Buduje graf zależności kodu (symbole, importy, wywołania)
- Utrzymuje persistent memory o projekcie (fakty, decyzje architektoniczne)
- Udostępnia 2-pasmowe retrieval (semantic + structural graph)
- Zapewnia API + CLI do Q&A i "co-pilot architekt"
- Wystawia MCP server z narzędziami core + plugin tools
- Wspiera system pluginów instalowanych z GitHuba

**To jest nowy, czysty projekt** — niepowiązany z istniejącymi aplikacjami (trading, RAG, mcp-servers).
Żyje w `kontekst ai/` jako samodzielny stack.
Ollama działa lokalnie na Windows (localhost:11434).
Repo do indeksowania podaje się jako argument: `ai_repo index --repo-path /ścieżka/do/repo`.

---

## Decyzje techniczne

| Decyzja | Wybór | Uzasadnienie |
|---------|-------|--------------|
| Język | Python (FastAPI) | Repo jest pythonowe, reuse wzorców z RAG/ |
| Parser kodu | `ast` (stdlib) + `yaml.safe_load` + regex | Zero deps dla Pythona, najszybszy i najniezawodniejszy |
| Embeddingi | Ollama `nomic-embed-text` (768 dim) | Lokalny, offline-first |
| LLM | Ollama (qwen3:4b lub 8b) | Lokalne modele 4B-8B |
| BM25 | PostgreSQL `tsvector` + `ts_rank` | Zero deps, istniejący indeks GIN |
| Re-ranking | BM25 score + cosine similarity → RRF (k=60) | Prosty, bez ciężkich modeli |
| DB | PostgreSQL 16 + pgvector (port 5435) | Osobna instancja, nie koliduje z n8n(5432)/trading(5433)/RAG(5434) |
| MCP | JSON-RPC 2.0 over stdio + HTTP SSE | Standard MCP protocol |

---

## Struktura katalogów (docelowa)

```
kontekst ai/
├── docker-compose.ai-repo.yml    # Postgres + pgvector
├── config.yaml                    # Główna konfiguracja
├── .env.example                   # Zmienne środowiskowe
├── Makefile                       # make ai-up, ai-index, ai-api, ai-query, ai-graph
├── README_AI_REPO.md              # Dokumentacja
│
├── ai_repo/                       # Główna aplikacja
│   ├── __init__.py
│   ├── __main__.py                # CLI entry point (python -m ai_repo ...)
│   ├── cli.py                     # Typer CLI: index, query, graph, explain, plugin
│   ├── config.py                  # Pydantic settings z .env + config.yaml
│   │
│   ├── api/                       # FastAPI server
│   │   ├── __init__.py
│   │   ├── server.py              # FastAPI app, CORS, lifespan
│   │   ├── routes/
│   │   │   ├── query.py           # POST /query, POST /explain
│   │   │   ├── graph.py           # GET /graph/neighbors, GET /graph/impact
│   │   │   ├── memory.py          # GET/POST /memory
│   │   │   └── system.py          # GET /health, GET /stats
│   │   └── mcp/
│   │       ├── server.py          # MCP JSON-RPC handler
│   │       ├── tools.py           # Core tool definitions
│   │       └── registry.py        # Tool registry (core + plugins)
│   │
│   ├── core/                      # Core business logic
│   │   ├── __init__.py
│   │   ├── database.py            # SQLAlchemy models + pgvector
│   │   ├── indexer.py             # Repo scanner, incremental (git diff + mtime)
│   │   ├── chunker.py             # Code-aware chunking (po funkcjach/klasach)
│   │   ├── embeddings.py          # Ollama embedding client
│   │   ├── llm.py                 # Ollama LLM + Anthropic fallback
│   │   ├── graph_builder.py       # AST walker → symbole + edges
│   │   ├── retriever.py           # Dual retrieval: semantic + graph
│   │   ├── reranker.py            # BM25 + cosine + RRF
│   │   ├── memory.py              # Project memory manager
│   │   └── prompt_composer.py     # Buduje kontekst z chunks + graph + memory
│   │
│   ├── parsers/                   # Parsery per język/typ pliku
│   │   ├── __init__.py
│   │   ├── python_parser.py       # ast.NodeVisitor → symbole + deps
│   │   ├── yaml_parser.py         # docker-compose, config.yaml
│   │   ├── dockerfile_parser.py   # FROM, COPY, RUN
│   │   ├── sql_parser.py          # CREATE TABLE, REFERENCES
│   │   └── generic_parser.py      # requirements.txt, .env, markdown
│   │
│   └── plugins/                   # Plugin system
│       ├── __init__.py
│       ├── loader.py              # Plugin discovery + loading
│       ├── sandbox.py             # Permission sandbox
│       ├── installer.py           # git clone + pin to commit/tag
│       └── base.py                # PluginBase class, PluginContext
│
├── migrations/                    # SQL schema
│   ├── 001_init.sql               # Core tables + pgvector extension
│   ├── 002_graph.sql              # symbols + edges tables
│   └── 003_memory.sql             # project_memory + retrieval_logs
│
├── plugins/                       # Installed + example plugins
│   ├── README.md                  # Jak pisać pluginy
│   ├── _vendor/                   # Pluginy pobrane z GitHuba
│   └── examples/
│       └── plugin-template/       # Szablon pluginu
│           ├── plugin.yaml
│           ├── __init__.py
│           └── tools.py
│
├── plugin-logs/                   # Wbudowany plugin logów
│   ├── plugin.yaml
│   ├── __init__.py
│   └── tools.py                   # logs.top_errors, logs.trace_request, etc.
│
└── tests/                         # Testy minimalne
    ├── test_parser.py             # AST parser test
    ├── test_db.py                 # DB insert + query test
    └── test_retrieval.py          # Retrieval pipeline test
```

---

## Fazy implementacji

### FAZA 1: Infrastruktura (docker-compose + DB + config)
**Pliki**: `docker-compose.ai-repo.yml`, `migrations/001_init.sql`, `002_graph.sql`, `003_memory.sql`, `.env.example`, `config.yaml`, `Makefile`

1. Docker Compose z PostgreSQL 16 + pgvector (port 5435)
2. SQL migracje — 6 tabel:
   - `documents(id, path, type, hash, mtime, repo_id)`
   - `chunks(id, document_id, chunk_index, content, start_line, end_line, tokens, embedding vector(768))`
   - `symbols(id, name, kind, file_path, start_line, end_line, signature, docstring)`
   - `edges(id, src_kind, src_id, dst_kind, dst_id, edge_type, weight)`
   - `project_memory(id, key, value, confidence, updated_at, tags text[])`
   - `retrieval_logs(id, query, topk, latency_ms, provider_used, context_tokens, created_at)`
3. Indeksy: HNSW na `chunks.embedding`, GIN na `to_tsvector('simple', content)`, B-tree na `documents.path`, `symbols.file_path`
4. Config (Pydantic): `ai_repo/config.py` ładujący `.env` + `config.yaml`
5. Makefile targets: `ai-up`, `ai-down`, `ai-migrate`

### FAZA 2: Core — Indexer + Parsery + Graph Builder
**Pliki**: `ai_repo/core/indexer.py`, `ai_repo/core/chunker.py`, `ai_repo/core/graph_builder.py`, `ai_repo/parsers/*.py`, `ai_repo/core/database.py`

1. **Database models** (SQLAlchemy) dla 6 tabel
2. **Indexer** (`core/indexer.py`):
   - Skanuje repo rekurencyjnie (respektuje `.gitignore` + filtry: `node_modules`, `.venv`, `dist`, `__pycache__`)
   - Incremental: porównuje `mtime` + `SHA-256` z DB, re-parsuje tylko zmienione pliki
   - Pipeline: scan → parse → chunk → upsert documents/chunks
3. **Code-aware chunker** (`core/chunker.py`):
   - Dla Pythona: chunk per klasa/funkcja (z docstringiem)
   - Fallback: sliding window 512 tokens, 128 overlap
   - Zachowuje `start_line`, `end_line`
4. **Python parser** (`parsers/python_parser.py`):
   - `ast.NodeVisitor` walker — ekstrakcja: klasy, funkcje, importy, wywołania, dziedziczenie
   - Resolver importów relatywnych → absolute file paths
5. **YAML/Dockerfile/SQL/Generic parsery** — proste regex + `yaml.safe_load`
6. **Graph builder** (`core/graph_builder.py`):
   - Zbiera wyniki z parserów → INSERT INTO symbols + edges
   - Edge types: `import`, `call`, `inheritance`, `depends_on`, `config_ref`

### FAZA 3: Embeddingi + LLM + Retrieval
**Pliki**: `ai_repo/core/embeddings.py`, `ai_repo/core/llm.py`, `ai_repo/core/retriever.py`, `ai_repo/core/reranker.py`, `ai_repo/core/prompt_composer.py`

1. **Embedding client** (`core/embeddings.py`):
   - HTTP do Ollama `POST /api/embed` z modelem `nomic-embed-text`
   - Batch processing (grupy po 32 chunki)
   - Retry + timeout handling
2. **LLM client** (`core/llm.py`):
   - Ollama: `POST /api/generate` (streaming)
   - Anthropic fallback: jeśli `ANTHROPIC_API_KEY` + `llm_provider=anthropic` w config
   - Abstrakcja: `generate(prompt, system, temperature)` → `AsyncIterator[str]`
3. **Retriever** (`core/retriever.py`):
   - Pas A: Semantic search — `pgvector` cosine similarity na `chunks.embedding`, top-50
   - Pas B: Keyword search — PostgreSQL `tsvector` + `ts_rank`, top-50
   - Pas C: Graph expansion — dla top wyników, rozszerz o sąsiadów w grafie (importy, wywołania)
4. **Re-ranker** (`core/reranker.py`):
   - Reciprocal Rank Fusion (RRF, k=60) na wynikach semantic + keyword
   - Bonus za graph distance (bliższe symbole w grafie → wyższy score)
   - Zwraca top-10
5. **Prompt composer** (`core/prompt_composer.py`):
   - Zbiera: memory facts + top chunks (z ścieżkami + liniami) + graph context
   - Formatuje system prompt z instrukcjami cytowania plików
   - Limit context tokens (4096 domyślnie, konfigurowalny)

### FAZA 4: Project Memory + Auto-bootstrap
**Pliki**: `ai_repo/core/memory.py`

1. **Memory manager** (`core/memory.py`):
   - CRUD na `project_memory` (key-value z confidence + tags)
   - `memory_sources` — link do dokumentu/symbolu źródłowego
2. **Auto-bootstrap**: po pierwszym `ai_repo index`:
   - Wygeneruj "Project Map" przez LLM:
     - Moduły i ich odpowiedzialności
     - Usługi (z docker-compose)
     - Bazy danych (z SQL/config)
     - Entrypointy (main, app.py, __main__.py)
     - Zmienne środowiskowe (z .env)
     - Krytyczne przepływy (na podstawie grafu)
   - Zapisz jako fakty do `project_memory`

### FAZA 5: API + CLI
**Pliki**: `ai_repo/api/server.py`, `ai_repo/api/routes/*.py`, `ai_repo/cli.py`, `ai_repo/__main__.py`

1. **FastAPI server** (`api/server.py`):
   - `POST /api/v1/query` — pytanie + retrieval + LLM odpowiedź
   - `POST /api/v1/explain` — wyjaśnij zmianę/plik
   - `GET /api/v1/graph/neighbors/{symbol}` — sąsiedzi w grafie
   - `GET /api/v1/graph/impact/{symbol}` — impact analysis
   - `GET/POST /api/v1/memory` — odczyt/zapis project memory
   - `GET /api/v1/health` — healthcheck
   - `GET /api/v1/stats` — statystyki (docs, chunks, symbols, edges)
2. **CLI** (`cli.py` z Typer):
   - `ai_repo index [--repo-path] [--incremental]` — indeksuj repo
   - `ai_repo query "pytanie"` — zadaj pytanie
   - `ai_repo graph [symbol]` — pokaż graf zależności
   - `ai_repo explain [file_path]` — wyjaśnij plik/zmianę
   - `ai_repo memory list|get|set` — zarządzaj memory
   - `ai_repo plugin install|list|remove` — zarządzaj pluginami
3. **Makefile targets**: `ai-index`, `ai-api`, `ai-query`, `ai-graph`

### FAZA 6: MCP Server
**Pliki**: `ai_repo/api/mcp/server.py`, `ai_repo/api/mcp/tools.py`, `ai_repo/api/mcp/registry.py`

1. **MCP protocol** (JSON-RPC 2.0):
   - Endpointy: `tools/list`, `tools/call`
   - Transport: stdio (dla Claude Code) + HTTP SSE (dla innych klientów)
2. **Core tools**:
   - `repo.search` — semantic + keyword search
   - `repo.graph_neighbors` — sąsiedzi symbolu w grafie
   - `repo.impact_analysis` — co się złamie jeśli zmienię X
   - `repo.memory_get` — odczytaj fakt z memory
   - `repo.memory_set` — zapisz fakt do memory
   - `repo.explain` — wyjaśnij plik/symbol/zmianę
3. **Tool registry** (`mcp/registry.py`):
   - Rejestruje core tools
   - Dynamicznie dodaje plugin tools (FAZA 7)
   - Thread-safe, lazy loading

### FAZA 7: Plugin System
**Pliki**: `ai_repo/plugins/*.py`, `plugins/README.md`, `plugins/examples/plugin-template/`, `plugin-logs/`

1. **Plugin interface** (`plugins/base.py`):
   - `PluginBase` abstract class z `register(context) → list[ToolHandler]`
   - `PluginContext` — daje pluginowi dostęp do DB, retriever, memory (read-only domyślnie)
2. **Plugin manifest** (`plugin.yaml`):
   ```yaml
   name: plugin-template
   version: 0.1.0
   entrypoint: tools.py
   required_env: []
   permissions:
     filesystem: read_only
     network: false
   tools:
     - name: template.hello
       description: "Example tool"
   ```
3. **Plugin loader** (`plugins/loader.py`):
   - Skanuje `plugins/` + `plugins/_vendor/`
   - Waliduje manifest, sprawdza permissions vs config allowlist
   - Importuje entrypoint, wywołuje `register(context)`
   - Rejestruje tools w MCP registry
4. **Plugin installer** (`plugins/installer.py`):
   - `ai_repo plugin install <git_url>@<ref>`
   - `git clone --depth 1 --branch <ref>` do `plugins/_vendor/<name>/<ref>/`
   - Zapisuje checksum, pin do commita
   - `ai_repo plugin list` — lista zainstalowanych
   - `ai_repo plugin remove <name>` — usuwanie
5. **Plugin sandbox** (`plugins/sandbox.py`):
   - Ograniczenie dostępu do FS (tylko repo dir)
   - Brak sieci domyślnie (chyba że permissions.network: true)
   - Allowlist w config.yaml
6. **Example plugin** (`plugins/examples/plugin-template/`):
   - Minimalny plugin z jednym narzędziem
   - Dokumentacja w docstringu
7. **Plugin-logs** (`plugin-logs/`):
   - Parsuje logi z plików
   - Structured events w Postgres: `log_events(ts, service, level, error_signature, trace_id, message, meta_json)`
   - Embedding tylko dla: `incident_summaries`, `error_signatures`, `window_summaries`
   - Tools: `logs.top_errors`, `logs.trace_request`, `logs.summarize_last_30m`, `logs.correlate_with_commit`
8. **CodeRabbit adapter**:
   - Endpoint `POST /api/v1/pr_context_bundle`
   - Input: `pr_id` (lub diff text)
   - Output: diff summary, top changed symbols, risk hotspots, relevant memory facts, optional plugin findings

### FAZA 8: Testy + Dokumentacja
**Pliki**: `tests/*.py`, `README_AI_REPO.md`

1. **Testy** (pytest):
   - `test_parser.py` — Python AST parser: ekstrakcja klas, funkcji, importów
   - `test_db.py` — insert document + chunk, query by vector
   - `test_retrieval.py` — full retrieval pipeline (mock embeddings)
2. **README_AI_REPO.md**:
   - Instalacja + wymagania (Docker, Ollama)
   - Quick start
   - Jak indeksować nowe repo
   - Jak działa incremental indexing
   - Jak pisać pluginy
   - Debugowanie

---

## Zależności Python (requirements.txt)

```
# Web framework
fastapi>=0.115.0
uvicorn[standard]>=0.34.0

# Database
sqlalchemy>=2.0.36
psycopg2-binary>=2.9.10
pgvector>=0.3.6

# CLI
typer>=0.12.0
rich>=13.0.0

# HTTP client (Ollama + Anthropic)
httpx>=0.28.0

# Config
pydantic-settings>=2.0.0
pyyaml>=6.0

# Token counting
tiktoken>=0.8.0

# Anthropic fallback (optional)
anthropic>=0.40.0

# MCP
mcp>=1.0.0

# Git operations
gitpython>=3.1.0

# Tests
pytest>=8.0.0
pytest-asyncio>=0.24.0
```

---

## Docker Compose (docker-compose.ai-repo.yml)

```yaml
services:
  ai-repo-postgres:
    image: pgvector/pgvector:pg16
    ports: ["5435:5432"]
    environment:
      POSTGRES_USER: ai_repo
      POSTGRES_PASSWORD: ai_repo_pass
      POSTGRES_DB: ai_repo
    volumes:
      - ai_repo_pgdata:/var/lib/postgresql/data
      - ./migrations:/docker-entrypoint-initdb.d
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ai_repo"]
      interval: 5s
      retries: 5

volumes:
  ai_repo_pgdata:
```

---

## Schemat danych (SQL)

### 001_init.sql
```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
    id SERIAL PRIMARY KEY,
    path TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'python',
    hash TEXT NOT NULL,
    mtime DOUBLE PRECISION NOT NULL,
    repo_id TEXT NOT NULL DEFAULT 'default',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(path, repo_id)
);

CREATE TABLE chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    start_line INTEGER,
    end_line INTEGER,
    tokens INTEGER,
    embedding vector(768),
    UNIQUE(document_id, chunk_index)
);

CREATE INDEX idx_chunks_embedding ON chunks
    USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64);
CREATE INDEX idx_chunks_content_fts ON chunks
    USING gin (to_tsvector('simple', content));
```

### 002_graph.sql
```sql
CREATE TABLE symbols (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL, -- class, function, variable, import, endpoint, table
    file_path TEXT NOT NULL,
    start_line INTEGER,
    end_line INTEGER,
    signature TEXT,
    docstring TEXT,
    UNIQUE(name, kind, file_path, start_line)
);

CREATE TABLE edges (
    id SERIAL PRIMARY KEY,
    src_kind TEXT NOT NULL,
    src_id INTEGER NOT NULL,
    dst_kind TEXT NOT NULL,
    dst_id INTEGER NOT NULL,
    edge_type TEXT NOT NULL, -- import, call, inheritance, depends_on, config_ref
    weight REAL DEFAULT 1.0,
    UNIQUE(src_id, dst_id, edge_type)
);

CREATE INDEX idx_symbols_file ON symbols(file_path);
CREATE INDEX idx_symbols_name ON symbols(name);
CREATE INDEX idx_edges_src ON edges(src_id);
CREATE INDEX idx_edges_dst ON edges(dst_id);
```

### 003_memory.sql
```sql
CREATE TABLE project_memory (
    id SERIAL PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    value TEXT NOT NULL,
    confidence REAL DEFAULT 0.8,
    tags TEXT[] DEFAULT '{}',
    source TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE retrieval_logs (
    id SERIAL PRIMARY KEY,
    query TEXT NOT NULL,
    topk INTEGER DEFAULT 10,
    latency_ms REAL,
    provider_used TEXT DEFAULT 'ollama',
    context_tokens INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- For plugin-logs structured events
CREATE TABLE log_events (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    service TEXT,
    level TEXT,
    error_signature TEXT,
    trace_id TEXT,
    message TEXT,
    meta_json JSONB DEFAULT '{}'
);

CREATE INDEX idx_log_events_ts ON log_events(ts);
CREATE INDEX idx_log_events_service ON log_events(service);
CREATE INDEX idx_log_events_signature ON log_events(error_signature);
```

---

## Weryfikacja (checklist po implementacji)

1. `make ai-up` → Postgres startuje na porcie 5435, tabele utworzone
2. `make ai-index` → indeksuje pliki z podanego repo, widać documents + chunks + symbols w DB
3. `make ai-api` → FastAPI serwer na porcie 8100, `/health` zwraca OK
4. `make ai-query "jak działa signal engine?"` → zwraca odpowiedź z cytowaniami plików
5. `make ai-graph` → wyświetla graf zależności dla wskazanego symbolu
6. MCP `tools/list` → zwraca core + plugin tools
7. `ai_repo plugin list` → lista pluginów (plugin-logs + template)
8. `pytest tests/` → 3 testy przechodzą

---

## Ryzyka i mitygacja

| Ryzyko | Mitygacja |
|--------|-----------|
| Port 5435 zajęty | Konfigurowalny w .env |
| Ollama nie zainstalowane | Graceful degradation — indexing działa bez embeddingów, query zwraca BM25-only |
| Duże repo = wolny indexing | Incremental (mtime+hash), filtrowanie `.gitignore` |
| Plugin z GitHuba = security risk | Sandbox (no FS outside repo, no network), allowlist permissions |
| Brak GPU na Windows = wolne embeddingi | nomic-embed-text działa na CPU (jest mały), batch processing |

---

## Kolejność implementacji

Implementuję **sekwencyjnie** w 8 fazach, każda daje działający milestone:
1. Infra → 2. Indexer/Parsery → 3. Embeddingi/Retrieval → 4. Memory → 5. API/CLI → 6. MCP → 7. Plugins → 8. Testy/Docs

Każda faza jest testowalna niezależnie.
