# RAG System — Progress Tracker

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

### FAZA 3: AI Integration (wymaga Mac Studio)
- [ ] **3.1** `core/embeddings.py` — Ollama embedding client (remote)
- [ ] **3.2** `core/llm.py` — Ollama LLM client (remote, streaming)
- [ ] **3.3** `docker-compose-ai.yml` — Ollama config dla Mac Studio
- [ ] **3.4** `ai-services/whisper-server/` — FastAPI wrapper dla mlx-whisper
- [ ] **3.5** `ingestion/whisper.py` — klient remote mlx-whisper
- [ ] **3.6** Smoke test: embed tekst, generate odpowiedź, transkrybuj audio

### FAZA 4: RAG Pipeline
- [ ] **4.1** `core/retriever.py` — hybrid search (semantic + BM25 + RRF)
- [ ] **4.2** `core/rewriter.py` — query rewriting (conversational context)
- [ ] **4.3** `core/judge.py` — LLM-as-judge (groundedness, completeness)
- [ ] **4.4** `services/chat_service.py` — pełny pipeline: query → retrieve → generate → validate
- [ ] **4.5** `api/routes/chat.py` — SSE streaming endpoint
- [ ] **4.6** `services/profile_service.py` — interest tracking
- [ ] **4.7** `services/ranker_agent.py` — background quality evaluator
- [ ] **4.8** Smoke test: zadaj pytanie → streaming odpowiedź z cytatami

### FAZA 5: Web Crawling (mdream)
- [ ] **5.1** mdream (`harlanzw/mdream`) w docker-compose-app.yml
- [ ] **5.2** `ingestion/crawler.py` — mdream client (HTML→Markdown, @mdream/crawl)
- [x] **5.3** `tasks/crawl_tasks.py` — placeholder done
- [ ] **5.4** Smoke test: podaj URL → markdown w DB, strona zindeksowana

### FAZA 6: Frontend (React + TypeScript)
- [ ] **6.1** Vite + React + TS + Tailwind + shadcn/ui scaffold
- [ ] **6.2** Layout: Sidebar + MainArea + routing
- [ ] **6.3** Auth: login page, JWT storage, protected routes
- [ ] **6.4** Chat view: input, message bubbles, SSE streaming, sources panel
- [ ] **6.5** Documents view: lista, upload drag-and-drop, processing status
- [ ] **6.6** Collections: folder tree, tag manager, chat context picker
- [ ] **6.7** Admin/Profile views
- [ ] **6.8** `frontend/Dockerfile` + nginx + dodanie do docker-compose
- [ ] **6.9** Smoke test: pełny flow UI → upload → chat → odpowiedź z cytatami

### FAZA 7: Benchmark & Tuning
- [ ] **7.1** `tasks/benchmark_tasks.py` — embedding benchmark framework
- [ ] **7.2** Test set (50 pytań PL/EN)
- [ ] **7.3** Benchmark run + wyniki
- [ ] **7.4** Finalny wybór modelu embeddingowego
- [ ] **7.5** LangFuse integration + tracing

### FAZA 8: Polish & Hardening
- [ ] **8.1** Backup script (pg_dump cron)
- [ ] **8.2** Error handling audit
- [ ] **8.3** Rate limiting na inference server
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

---

## Następna sesja: START HERE

**Prereq**: Uruchom Docker Desktop → `cd RAG && docker compose -f docker-compose-infra.yml -f docker-compose-app.yml up -d`

**Stan**: FAZA 0 ✅, FAZA 1 ✅, FAZA 2 ✅ — pipeline upload→parse→chunk→DB działa

**Zadanie 1**: FAZA 3 — AI Integration (wymaga Mac Studio w sieci LAN)
- 3.1: `core/embeddings.py` — Ollama embedding client (HTTP do Mac Studio)
  - Endpoint: `POST http://<mac-studio-ip>:11434/api/embeddings`
  - Model: do ustalenia po benchmarku (nomic-embed-text jako default)
  - Dodać embedding step do `document_tasks.py` pipeline (po chunk → embed → pgvector)
- 3.2: `core/llm.py` — Ollama LLM client (streaming)
  - Endpoint: `POST http://<mac-studio-ip>:11434/api/generate` (streaming)
  - Model: qwen3:latest
- 3.3: `docker-compose-ai.yml` — Ollama config dla Mac Studio
- 3.4: `ai-services/whisper-server/` — FastAPI wrapper dla mlx-whisper
- 3.5: `ingestion/whisper.py` — klient remote mlx-whisper
- 3.6: Smoke test: embed tekst, generate odpowiedź, transkrybuj audio

**Opcjonalnie**: Przetestować pipeline z prawdziwym PDF (nie tylko .md)

**Pliki do przeczytania**: `RAG/RAG.MD` sekcje 3.3, 3.4 (embedding, LLM)

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
