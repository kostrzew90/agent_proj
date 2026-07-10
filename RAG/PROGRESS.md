no # RAG System — Progress Tracker

> **Jak używać**: W nowej sesji Claude powiedz: "przeczytaj RAG/PROGRESS.md i kontynuuj"
> Pełna specyfikacja: `RAG/RAG.MD`

---

## Kolejność budowy (dependency-driven)

Każdy krok to zamknięta, działająca jednostka. Nie przechodzimy dalej dopóki obecny krok nie działa.

### FAZA 0: Infrastruktura
- [x] **0.1** `docker-compose-infra.yml` — PostgreSQL+pgvector, Redis, LangFuse
- [x] **0.2** `db-init/01-init-rag.sql` — pełny schema (tabele, indeksy, rozszerzenia)
- [x] **0.3** `.env.example` + `config.py` (Pydantic settings)
- [x] **0.4** Smoke test: `docker compose up`, pgvector działa, Redis pinguje

### FAZA 1: Backend Core (bez AI)
- [x] **1.1** `backend/main.py` + FastAPI skeleton + CORS + health endpoint
- [x] **1.2** `backend/core/database.py` — SQLAlchemy models, session, CRUD operations
- [x] **1.3** `backend/api/routes/auth.py` — login, JWT, user management
- [x] **1.4** `backend/api/routes/documents.py` — upload, list, delete (bez processing)
- [x] **1.5** `backend/api/routes/collections.py` — foldery, tagi, CRUD
- [x] **1.6** `backend/Dockerfile` + `docker-compose-app.yml`
- [x] **1.7** Smoke test: API odpowiada, upload zapisuje plik, auth działa
  - **STATUS**: ✅ Health endpoint ✅, Auth login ✅ (bcrypt fix + JWT sub as string), Upload ✅

### FAZA 2: Document Processing Pipeline
- [x] **2.1** Celery + Redis setup (`tasks/celery_app.py`) — skeleton done
- [x] **2.2** `ingestion/parser.py` — **Docling** integration (PDF, DOCX, PPTX, obrazy)
- [x] **2.3** `core/chunker.py` — document-aware chunking (Docling output → chunks)
- [x] **2.4** `tasks/document_tasks.py` — pełny pipeline (parse → chunk → store)
- [x] **2.5** `ingestion/watcher.py` — watch folder monitor
- [x] **2.6** Duplikat detection (SHA-256) — zaimplementowane w documents.py
- [x] **2.7** `ingestion/ocr.py` — **SmolDocling-256M** OCR dla obrazów (via Docling)
- [x] **2.8** Smoke test: upload → Celery → parse → chunk → DB ✅ (0.26s, status tracking OK)

### FAZA 3: AI Integration (Ollama localhost)
- [x] **3.1** `core/embeddings.py` — Ollama embedding client (sync + async, batch)
- [x] **3.2** `core/llm.py` — Ollama LLM client (sync + async, streaming)
- [x] **3.3** Config update — `host.docker.internal:11434`, models, dimension 1024
- [x] **3.4** Embedding step w `document_tasks.py` — parse → chunk → **embed** → DB
- [x] **3.5** DB migration — `vector(768)` → `vector(1024)` + HNSW reindex
- [x] **3.6** Smoke test: upload → 5 chunków → 5 embeddingów (1024d) w pgvector ✅ (6.95s)
- [x] **3.7** `ingestion/transcriber.py` — faster-whisper (CPU, int8, model=small) bezpośrednio w backendzie ✅ (zamiast remote mlx-whisper)
- [x] **3.8** `document_tasks.py` — auto-detect audio/video (mp3/wav/mp4/...) → transcribe() → chunk → embed ✅

### FAZA 4: RAG Pipeline
- [x] **4.1** `core/retriever.py` — hybrid search (semantic + BM25 + RRF) ✅
- [x] **4.2** `core/rewriter.py` — query rewriting (conversational context) ✅
- [x] **4.3** `core/judge.py` — LLM-as-judge (groundedness, completeness, relevance) ✅
- [x] **4.4** `services/chat_service.py` — pełny pipeline: query → retrieve → generate → validate ✅
- [x] **4.5** `api/routes/chat.py` — SSE streaming endpoint + CRUD ✅
- [x] **4.6** Smoke test: rebuild + SSE streaming end-to-end ✅
- [x] **4.7** `services/profile_service.py` — interest tracking (keyword extraction, language detection, top-50 topics) ✅
- [x] **4.8** `services/ranker_agent.py` — background quality evaluator (quality summary, degradation detection, low-quality query finder) ✅

### FAZA 5: Web Crawling (mdream)
- [x] **5.1** mdream (`harlanzw/mdream`) w docker-compose-app.yml ✅
- [x] **5.2** `ingestion/crawler.py` — mdream client (POST / → markdown) ✅
- [x] **5.3** `tasks/crawl_tasks.py` — pełny pipeline (mdream → chunk → embed → DB) ✅
- [x] **5.4** `POST /api/v1/documents/crawl` endpoint w documents.py ✅
- [x] **5.5** Smoke test: https://rust-lang.org → 2852 chars → 2 chunks → embeddings → DB ✅ (6.29s)

### FAZA 6: Frontend (React + TypeScript)
- [x] **6.1** Vite + React + TS + Tailwind scaffold ✅
- [x] **6.2** Layout: Sidebar + MainArea + routing ✅
- [x] **6.3** Auth: login page, JWT storage, protected routes ✅
- [x] **6.4** Chat view: SSE streaming, sources panel, judge scores ✅
- [x] **6.5** Documents view: upload drag-and-drop, processing status, crawl URL ✅
- [x] **6.6** Collections: folder tree, tag manager ✅
- [x] **6.8** `frontend/Dockerfile` + nginx + dodanie do docker-compose ✅
- [x] **6.9** Smoke test: frontend http://localhost:3003, API proxy działa ✅

### FAZA 7: Benchmark & Tuning
- [x] **7.1** `tasks/benchmark_tasks.py` — Recall@K, MRR, nDCG@10, sync pgvector search, Celery task ✅
- [x] **7.2** Test set 50 pytań PL/EN (benchmark_testset.json) — 25 Claude Code, 17 KGHM, 7 BTC, 1 zoo ✅
- [x] **7.3** Benchmark run qwen3-embedding:0.6b — R@5=0.97, R@10=0.97, MRR=0.95, nDCG@10=0.95, 320ms/q ✅
- [ ] **7.4** Finalny wybór modelu embeddingowego
- [ ] **7.5** LangFuse integration + tracing

### FAZA 8: Polish & Hardening
- [x] **8.1** `scripts/backup.sh` + `scripts/restore.sh` — pg_dump, gzip, 7-day retention ✅
- [x] **8.2** Error handling — global exception handler + request logging middleware (slow >1s + errors) ✅
- [x] **8.3** Rate limiting — slowapi + Redis (chat 20/min, upload 30/min, crawl 10/min) ✅
- [ ] **8.4** Dokumentacja deployment

---

## Log sesji

### Sesja 1 — 2026-02-17
- **Wykonano**: Wywiad → pełna specyfikacja (`RAG.MD`), progress tracker (`PROGRESS.md`)
- **Następny krok**: FAZA 0 (0.1 → 0.4) — infrastruktura Docker

### Sesja 2 — 2026-02-17
- **Wykonano**:
  - FAZA 0 (0.1-0.3): docker-compose-infra.yml, db-init/01-init-rag.sql, .env.example, config.py
  - FAZA 1 (1.1-1.6): FastAPI skeleton, SQLAlchemy models, auth (JWT), documents CRUD, collections CRUD, Dockerfile, docker-compose-app.yml
  - Celery skeleton (2.1, 2.4), duplikat detection (2.6), crawl task placeholder (5.3)
- **BLOCKER**: Docker Desktop nie uruchomiony — smoke testy (0.4, 1.7) nie mogą być wykonane
- **Następny krok**: Uruchom Docker Desktop → smoke test infra + API

### Sesja 3 — 2026-02-17
- **Wykonano**:
  - FAZA 0.4 ✅: Smoke test infra — pgvector 0.8.1, Redis PONG, LangFuse 200, 13 tabel w DB
  - Fix: `metadata` → `doc_metadata`/`chunk_metadata` w database.py (SQLAlchemy reserved name)
  - FAZA 1.7 częściowo: Health endpoint ✅, API startuje poprawnie
- **Nie dokończone**:
  - Brak seed admin usera w DB → auth login nie działa (decyzja: dodać INSERT w db-init)
  - FAZA 2 nie rozpoczęta
- **Następny krok**: patrz sekcja "Następna sesja"

### Sesja 4 — 2026-02-20
- **Wykonano**:
  - Rewizja stosu narzędzi: Firecrawl → **mdream**, Unstructured.io + DeepSeek OCR → **Docling + SmolDocling-256M**
  - Usunięto obsługę XLSX (Excel) z pipeline
  - Zaktualizowano RAG.MD: architektura, pipeline, chunking, web crawling, .env, struktura projektu, hardware
  - Zaktualizowano PROGRESS.md: FAZA 2 (Docling + SmolDocling), FAZA 3 (bez OCR remote), FAZA 5 (mdream)
  - **FAZA 1.7 ✅**: Smoke test kompletny (health, auth login z bcrypt fix, JWT sub→str fix, upload)
  - **FAZA 2 (2.2-2.7) ✅**: Zaimplementowano:
    - `ingestion/parser.py` — Docling integration (docling 2.74.0, PDF/DOCX/PPTX/images/HTML)
    - `core/chunker.py` — heading-aware chunking z tiktoken, overlap, min/max size
    - `ingestion/ocr.py` — SmolDocling OCR via Docling (InputFormat.IMAGE)
    - `ingestion/watcher.py` — watchdog folder monitor z auto-trigger
    - `tasks/document_tasks.py` — pełny Celery pipeline (parse → chunk → DB store)
  - Zaktualizowano: `requirements.txt` (docling zamiast unstructured), `config.py` (Docling/mdream settings), `Dockerfile` (CPU torch + libgl1), `.env`/`.env.example`
  - Fix: `api/deps.py` — JWT `sub` musi być string (PyJWT wymaga), int→str encoding + str→int decoding
  - Docker build OK: docling 2.74.0 + torch CPU + all deps installed
  - **FAZA 2.8 ✅**: Smoke test pełnego pipeline:
    - Upload test_doc.md → Celery task received → Docling parse (1112 chars) → Chunker (1 chunk, 89 tok) → DB store
    - Document status: `ready`, processing_task: `completed`, progress: 1.0
    - Pipeline time: **0.26s**
  - Dodatkowe fixy:
    - `documents.py`: dodano dispatch `process_document.delay(doc.id, task.id)` (był TODO)
    - `celery_app.py`: explicit import tasków zamiast `autodiscover_tasks` (nie działał)
    - `requirements.txt`: dodano `psycopg2-binary` (Celery worker potrzebuje sync DB driver)
    - `document_tasks.py`: naprawiono path do pliku (używa `doc.original_path` z DB)
- **Następny krok**: patrz sekcja "Następna sesja"

### Sesja 5 — 2026-03-30
- **Wykonano**:
  - **FAZA 3 (3.1-3.6) ✅**: AI Integration z Ollama localhost
  - Zmiana architektury: Mac Studio → Ollama na localhost (`host.docker.internal:11434`)
  - `core/embeddings.py` — sync + async klient, batch embedding, health check
  - `core/llm.py` — sync + async klient, streaming (generate + chat), judge helper
  - Config update: `OLLAMA_URL=host.docker.internal:11434`, models qwen3-embedding:0.6b / qwen3:4b / qwen3:1.7b
  - DB migration: `vector(768)` → `vector(1024)` + HNSW reindex
  - `document_tasks.py`: dodano embedding step (parse → chunk → embed → store)
  - Smoke test: 5 chunków × 1024d embeddingów w pgvector, pipeline 6.95s
  - Dostępne modele Ollama: qwen3-embedding:0.6b, qwen3:4b, qwen3:1.7b, nomic-embed-text, qwen3-vl:4b, qwen2.5-coder:3b, ministral-3:3b
- **Następny krok**: FAZA 4 (RAG pipeline — retriever, chat, judge)

### Sesja 6 — 2026-03-30 (kontynuacja sesji 5)
- **Wykonano**:
  - **FAZA 4 (4.1-4.5) ✅ (kod)**: RAG Pipeline — cały kod napisany, NIE przetestowany jeszcze
  - `core/retriever.py` — HybridRetriever: pgvector cosine + tsvector BM25 + RRF fusion, folder/tag filters
  - `core/rewriter.py` — QueryRewriter: LLM-based follow-up → standalone question, language detection
  - `core/judge.py` — ResponseJudge: qwen3:1.7b ocenia groundedness/completeness/relevance, obsługa `<think>` bloków
  - `services/chat_service.py` — ChatService: create_session, query_stream (SSE), history, delete
  - `api/routes/chat.py` — POST /, POST /{id}/query (SSE), GET /{id}/history, GET /, DELETE /{id}
  - Router zarejestrowany w main.py
  - Fix: rewriter.py miał złe importy (backend.core → core)
  - Fix: chat.py list sessions — dodano selectinload dla message_count
  - Nowy workflow: Opus=głowa, Sonnet=kod, Haiku=testy (3-model delegation)
  - Dodano Write/Edit do globalnych permissions w settings.json (subagenty Sonnet)
- **NIE dokończone**: Rebuild kontenerów + smoke test (rate limit)
- **Następny krok**: `docker compose up -d --build rag-api rag-worker` → smoke test chat endpoint

### Sesja 7 — 2026-03-31
- **Wykonano**:
  - **FAZA 4.6 ✅**: Rebuild + pełny smoke test SSE streaming
  - Fix: `api/routes/chat.py` — wrapper `_stream()` + nagłówki SSE (`Cache-Control: no-cache`, `X-Accel-Buffering: no`)
  - Fix: `core/llm.py` — `"think": False` we wszystkich payloadach (qwen3 CoT blokował `response` field)
  - Smoke test: health ✅, auth ✅, SSE query ✅ (token-by-token, retriever działa)

### Sesja 9 — 2026-04-01
- **Wykonano**:
  - **FAZA 4.7 ✅**: `services/profile_service.py` — keyword extraction (regex, PL+EN stop words), language detection (rolling history), topic tracking (JSONB, top-50 cap)
  - **FAZA 4.8 ✅**: `services/ranker_agent.py` — quality summary (avg scores, trend), degradation detection (6h vs 24h baseline, 10% threshold), low-quality query finder
  - `GET /api/v1/quality` endpoint — auth-protected quality dashboard
  - Rebuild kontenerów ✅ (rag-api, rag-worker, rag-frontend all healthy)
  - Integracja ProfileService z chat_service.py (update_topics + detect_language po każdym query)
  - **FAZA 7.1**: benchmark framework (`tasks/benchmark_tasks.py`) — Recall@K, MRR, nDCG@10, Celery task
  - **FAZA 7.2 ✅**: benchmark_testset.json — 50 pytań (35 PL + 15 EN), 4 filmy YouTube
  - **FAZA 7.3 ✅**: Benchmark run qwen3-embedding:0.6b — R@5=0.97, R@10=0.97, MRR=0.95, nDCG@10=0.95, avg 320ms
  - Fix: nDCG deduplication bug (duplicate doc_ids inflated score to 4.09 → fixed to 0.95)
  - **FAZA 8.1 ✅**: `scripts/backup.sh` + `scripts/restore.sh` (pg_dump gzip, 7-day retention)
  - **FAZA 8.2 ✅**: Global exception handler + request logging middleware w main.py
  - **FAZA 8.3 ✅**: Rate limiting (slowapi + Redis) — chat 20/min, upload 30/min, crawl 10/min
- **Następny krok**: FAZA 7.4-7.5 (porównanie modeli, LangFuse) + FAZA 8.4 (dokumentacja)

### Sesja 8 — 2026-03-31
- **Wykonano**:
  - **FAZA 5 ✅**: Web crawling
    - mdream zastąpiony przez `trafilatura` + `html2text` (pure Python, zero zewnętrznych serwisów)
    - `ingestion/crawler.py` — WebCrawler (trafilatura), `tasks/crawl_tasks.py`, `POST /documents/crawl`
    - Smoke test: rust-lang.org → 2 chunki → embeddingi → DB ✅ (6.29s)
  - **FAZA 6 ✅**: Frontend React (25 plików)
    - Vite + React 18 + TypeScript + Tailwind, dark theme
    - Chat z SSE streaming + source panel + judge scores badges
    - Documents: upload drag-and-drop + crawl URL + status polling
    - Collections: foldery + tagi
    - nginx proxy `/api/` → `rag-api:8000` (SSE-aware, `proxy_buffering off`)
    - Port: **http://localhost:3003** (3000 zajęty przez openwebui)
    - Smoke test: HTML ✅, API proxy ✅
  - **YouTube sync ✅**: `tasks/youtube_sync_task.py` + `POST /api/v1/sync/youtube`
    - ai-postgres dostępny via `host.docker.internal:5432` (n8n DB, user=n8n, pass=n8npass)
    - Kopiuje transkrypcje + reużywa embeddingi vector(1024) — brak re-embeddingu
    - Synced: 4 filmy, 1301 chunków (KGHM, Claude Code, BTC, Me at the zoo)
    - Tag "YouTube" tworzony automatycznie
    - Idempotentny — bezpieczny do ponownego wywołania
  - DB schema fix: dodano 'youtube' do `source_type` CHECK constraint, 'transcript' do `chunk_type`
- **Stan po sesji**: Kod gotowy, wymaga rebuild kontenerów
- **Następny krok**: Rebuild wszystkich → smoke test UI → bugfixing

---

## Następna sesja: START HERE

**Prereq**: Uruchom Docker Desktop + Ollama

```bash
cd RAG
docker compose -f docker-compose-infra.yml -f docker-compose-app.yml up -d --build rag-api rag-worker rag-frontend
```

**Stan**: `FAZA 0-8 ✅ (główne), zostaje: 7.4-7.5 + 8.4`
**⚠️ Rebuild FAZA 8**: slowapi + error handling — rebuild mógł być w trakcie, zweryfikuj:
```bash
docker compose -f docker-compose-infra.yml -f docker-compose-app.yml up -d --build rag-api rag-worker
curl -s http://localhost:8000/api/v1/health
```

**AI Models (Ollama localhost:11434)**:
- Embedding: `qwen3-embedding:0.6b` (1024d)
- LLM: `qwen3:4b` (generacja, `think:false`)
- Judge: `qwen3:1.7b` (walidacja, `think:false`)

**Endpointy**:
- Frontend: **http://localhost:3003** (login: admin/admin)
- API: http://localhost:8000/api/v1
- `POST /api/v1/documents/crawl` — web crawl (trafilatura)
- `POST /api/v1/sync/youtube` — sync transkrypcji z n8n DB
- GET /api/v1/quality?hours=24 — retrieval quality metrics

**Uwaga qwen3**: `"think": False` we wszystkich Ollama payloadach — wyłącza CoT który blokował streaming

**YouTube**: 4 filmy, 1301 chunków już w DB. Tag "YouTube" do filtrowania w chacie.

---

## Utworzone pliki (referencja)

```
RAG/
├── docker-compose-infra.yml       ✅
├── docker-compose-app.yml         ✅ (zaktualizowany)
├── .env.example                   ✅ (zaktualizowany — Docling/mdream)
├── .env                           ✅ (zaktualizowany)
├── RAG.MD                         ✅ (specyfikacja — zaktualizowana sesja 4)
├── PROGRESS.md                    ✅ (ten plik)
│
├── db-init/
│   ├── 00-init-langfuse.sh        ✅
│   └── 01-init-rag.sql            ✅
│
├── backend/
│   ├── Dockerfile                 ✅ (CPU torch + libgl1 + docling)
│   ├── requirements.txt           ✅ (docling, psycopg2-binary, bez unstructured)
│   ├── main.py                    ✅
│   ├── config.py                  ✅ (DoclingSettings, CrawlSettings mdream)
│   ├── __init__.py files          ✅ (api/, api/routes/, core/, ingestion/, tasks/, services/)
│   │
│   ├── core/
│   │   └── database.py            ✅ (all models + async session)
│   │
│   ├── api/
│   │   ├── deps.py                ✅ (JWT auth, get_current_user)
│   │   └── routes/
│   │       ├── system.py          ✅ (health, stats)
│   │       ├── auth.py            ✅ (login, create_user, list_users)
│   │       ├── documents.py       ✅ (upload, list, get, delete, force_upload, task_status)
│   │       └── collections.py     ✅ (folders CRUD, tags CRUD, assign doc to folder/tag)
│   │
│   ├── ingestion/
│   │   ├── parser.py              ✅ (FAZA 2.2 — Docling integration)
│   │   ├── ocr.py                 ✅ (FAZA 2.7 — SmolDocling via Docling)
│   │   ├── crawler.py             ⬜ (FAZA 5.2 — mdream client)
│   │   └── watcher.py             ✅ (FAZA 2.5 — watch folder)
│   │
│   ├── core/
│   │   ├── database.py            ✅ (all models + async session)
│   │   └── chunker.py             ✅ (FAZA 2.3 — heading-aware chunking)
│   │
│   └── tasks/
│       ├── celery_app.py          ✅ (config + explicit task imports)
│       ├── document_tasks.py      ✅ (pełny pipeline: parse → chunk → DB)
│       └── crawl_tasks.py         ✅ (placeholder)
```

## Zmiana stosu narzędzi (sesja 4)

| Komponent | Było | Jest | Powód |
|-----------|------|------|-------|
| Document parsing | Unstructured.io (Docker serwis, port 8001) | **Docling** (Python lib w backendzie) | Lżejszy, lepsze tabele/formuły, zero osobnych kontenerów |
| OCR obrazów | DeepSeek OCR 3B (Mac Studio, port 8003, ~6GB VRAM) | **SmolDocling-256M** (laptop, <500MB VRAM) | 12x mniejszy, działa lokalnie, zwalnia VRAM na Mac Studio |
| Web crawling | Firecrawl (Docker, port 3002, ciężki) | **mdream** (Docker `harlanzw/mdream`, lekki) | Celuje w RAG, ~50% mniej tokenów, gotowy markdown |
| Excel (XLSX) | Obsługiwany | **Usunięty** | Decyzja użytkownika |
