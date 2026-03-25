# RAG System — Pełna Specyfikacja Techniczna

## 1. Przegląd projektu

**Cel**: Uniwersalny asystent dokumentów z wielojęzycznym RAG pipeline, obsługujący multimodalne źródła danych (PDF, DOCX, PPTX, obrazy/OCR, audio/transkrypcja, strony www).

**Filozofia**: W pełni lokalny (self-hosted), zero danych na zewnątrz. Architektura rozdzielona — aplikacja na lekkim sprzęcie (laptop), inference AI na dedykowanym serwerze (Mac Studio M3 96GB).

**Użytkownicy**: Kilku zaufanych użytkowników z basic auth (user/pass).

---

## 2. Architektura wysokopoziomowa

```
┌─────────────────────────────────────────────────────────────────┐
│                    LAPTOP / LEKKI SERWER                        │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │  React + TS   │  │  FastAPI     │  │  Celery Workers        │ │
│  │  Frontend     │◄►│  + Docling   │◄►│  (document processing) │ │
│  │  (port 3000)  │  │  (port 8000) │  │  + SmolDocling OCR     │ │
│  └──────────────┘  └──────┬───────┘  └────────┬───────────────┘ │
│                           │                    │                 │
│  ┌──────────────┐  ┌──────┴───────┐  ┌────────┴───────────────┐ │
│  │  LangFuse    │  │  PostgreSQL  │  │  Redis                 │ │
│  │  (tracing)   │  │  + pgvector  │  │  (task queue + cache)  │ │
│  │  (port 3001) │  │  (port 5434) │  │  (port 6379)           │ │
│  └──────────────┘  └──────────────┘  └────────────────────────┘ │
│                                                                 │
│  ┌──────────────┐                                               │
│  │  mdream      │  Docling = Python lib w backendzie (nie       │
│  │  (web crawl  │  osobny serwis). SmolDocling-256M do OCR     │
│  │  + HTML→MD)  │  obrazów (<500MB VRAM, działa na CPU).       │
│  │  (Docker)    │                                               │
│  └──────────────┘                                               │
└─────────────────────────────────────────────────────────────────┘
                           │
                    ┌──────┴──────┐
                    │  SIEĆ LAN   │
                    └──────┬──────┘
                           │
┌─────────────────────────────────────────────────────────────────┐
│                    MAC STUDIO M3 (96GB)                          │
│                    (Inference Server)                            │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐                             │
│  │  Ollama      │  │  mlx-whisper │                             │
│  │  (LLM +      │  │  (transkryp- │                             │
│  │   embeddings)│  │   cja audio) │                             │
│  │  (port 11434)│  │  (port 8002) │                             │
│  └──────────────┘  └──────────────┘                             │
└─────────────────────────────────────────────────────────────────┘
```

### Deployment: 3 Docker Compose pliki

| Plik | Gdzie | Zawartość |
|------|-------|-----------|
| `docker-compose-infra.yml` | Laptop | PostgreSQL+pgvector, Redis, LangFuse |
| `docker-compose-app.yml` | Laptop | FastAPI+Docling, React frontend, Celery workers, mdream |
| `docker-compose-ai.yml` | Mac Studio | Ollama, mlx-whisper serwis |

---

## 3. Komponenty szczegółowo

### 3.1 Document Ingestion Pipeline

#### Obsługiwane formaty
- **Tekst**: PDF, DOCX, TXT, MD, CSV, RTF
- **Prezentacje**: PPTX
- **Obrazy (OCR)**: PNG, JPG, TIFF, BMP → SmolDocling-256M (lokalnie, <500MB VRAM)
- **Audio (transkrypcja)**: MP3, WAV, M4A, OGG, FLAC → mlx-whisper na Mac Studio
- **Web**: URL → mdream (Docker, obsługa JS/SPA via Playwright)

#### Metody uploadu
1. **UI drag-and-drop**: Upload przez React frontend z progress barem i statusem przetwarzania
2. **REST API**: `POST /api/v1/documents/upload` — programowy upload (multipart/form-data)
3. **Watch folder**: Monitorowany katalog (Docker volume mount) — nowe pliki auto-indeksowane

#### Pipeline przetwarzania
```
Upload → Dedup check (hash) → Parser (Docling) → Chunking → Embedding → pgvector
                                      │
                                      ├─ PDF/DOCX/PPTX → Docling (layout-aware, tabele, formuły)
                                      ├─ Obrazy → SmolDocling-256M OCR → tekst + struktura
                                      ├─ Audio → mlx-whisper → transkrypcja
                                      └─ URL → mdream (@mdream/crawl) → Markdown
```

#### Async processing
- **Celery + Redis** do obsługi ciężkich tasków (OCR, Whisper mogą trwać minuty)
- API zwraca `task_id`, frontend polluje status
- Auto-scaling/scheduling: interactive queries priorytetowe, batch processing (indeksowanie, Whisper) w tle
- Priority queue: chat queries > embedding > OCR/Whisper > web crawl

### 3.2 Chunking Strategy — Document-Aware

Różne strategie dla różnych typów dokumentów:

| Typ dokumentu | Strategia | Szczegóły |
|---------------|-----------|-----------|
| PDF | Per-sekcja/rozdział | Docling wykrywa layout, nagłówki, tabele, formuły. Fallback: per-strona |
| DOCX | Per-sekcja (heading-based) | Docling dzieli na granicy nagłówków (H1, H2, H3) |
| PPTX | Per-slajd | Docling: każdy slajd = chunk + notes |
| Kod | Per-funkcja/klasa | AST-based splitting |
| Audio transkrypcja | Per-segment (timecoded) | Zachowaj timestamps w metadata |
| Web (markdown) | Per-sekcja heading | mdream generuje czysty markdown, chunk po nagłówkach |

**Smart splitting** dla dużych dokumentów:
- Dokumenty >50 stron automatycznie dzielone na logiczne części (rozdziały)
- Każda część jako osobny "sub-dokument" w kolekcji
- Zachowanie hierarchii: dokument → część → sekcja → chunk

**Parametry chunkowania** (konfigurowalne):
- Target chunk size: 512 tokenów
- Overlap: 20% (102 tokeny)
- Max chunk size: 1024 tokenów
- Min chunk size: 64 tokenów

### 3.3 Embedding & Retrieval

#### Benchmark embeddingowy (przed wyborem modelu)
Testowane modele:
1. **Qwen embed 0.6B** — mały, tani w inference
2. **multilingual-e5-small** — sprawdzony multilingual
3. **nomic-embed-text** — dobry ogólny, dostępny w Ollama
4. **mxbai-embed-large** — większy, potencjalnie lepsza jakość

**Metodologia benchmarku**:
- Test set: 50 pytań (PL/EN/mixed) + oczekiwane dokumenty źródłowe
- Metryki: Recall@5, Recall@10, MRR (Mean Reciprocal Rank), nDCG@10
- Cross-lingual test: pytanie PL → dokument EN i odwrotnie
- **AI Agent Ranker**: dedykowany agent w tle, który ciągle ewaluuje jakość retrievalu na live queries i raportuje degradację

#### Hybrid Search: Semantic + BM25
```
Query → ┌─ Embedding search (pgvector, cosine similarity) → top-50
        └─ BM25 keyword search (pg_trgm / tsvector) → top-50
                    │
                    ▼
           Reciprocal Rank Fusion (RRF) → top-10
                    │
                    ▼
           (opcjonalny) Cross-encoder reranker → top-5
```

- **pgvector**: indeks HNSW dla approximate nearest neighbor
- **BM25**: PostgreSQL full-text search z `tsvector` + `ts_rank`
- **RRF**: łączy rankingi z obu metod bez potrzeby normalizacji score'ów
- **Metadata filters**: opcjonalne filtrowanie po folderze/tagu/dacie PRZED searchem

### 3.4 Generation (LLM)

#### Model
- **Primary**: Qwen3 przez Ollama na Mac Studio (rozmiar do ustalenia po benchmark hardware)
- **Komunikacja**: Dedykowany inference server (Ollama HTTP API) w sieci LAN

#### Strict Grounding — Zero Halucynacji
- LLM **NIGDY** nie odpowiada z wyuczonej wiedzy
- Jeśli brak odpowiedzi w dokumentach → "Nie znalazłem odpowiedzi w dostępnych dokumentach"
- System prompt wymusza: "Odpowiadaj WYŁĄCZNIE na podstawie poniższych fragmentów. Jeśli informacja nie jest w fragmentach, powiedz że nie wiesz."
- LLM-as-judge waliduje każdą odpowiedź pod kątem groundedness

#### Format odpowiedzi: Streaming JSON + Markdown
```
Event stream (SSE):
  data: {"type": "token", "content": "Na podstawie..."}
  data: {"type": "token", "content": " dokumentu..."}
  ...
  data: {"type": "done", "answer": "pełna odpowiedź markdown",
         "sources": [
           {"document": "umowa.pdf", "page": 5, "section": "§3.2", "chunk_id": "abc123"},
           {"document": "regulamin.docx", "page": 12, "section": "Rozdział 4", "chunk_id": "def456"}
         ],
         "confidence": 0.87,
         "groundedness_score": 0.92}
```

#### Cytowanie źródeł
- Każde twierdzenie w odpowiedzi oznaczone inline: `[1]`, `[2]`
- Na końcu lista źródeł: dokument + strona/sekcja
- UI umożliwia kliknięcie w cytat → podgląd oryginalnego fragmentu

### 3.5 Conversational RAG + Profile użytkownika

#### Pamięć konwersacji
- Historia rozmowy przechowywana w PostgreSQL (tabela `chat_sessions`, `chat_messages`)
- Query rewriting: follow-up pytania przepisywane z kontekstem rozmowy
  - Przykład: "A co z paragrafem 5?" → "Co mówi paragraf 5 umowy X w kontekście warunków rozwiązania?"
- Sliding window: ostatnie N wiadomości (konfigurowalne, domyślnie 10) jako kontekst

#### Profile użytkowników
- **Historia zainteresowań**: system śledzi często pytane tematy
- Tabela `user_profiles` z polami:
  - `frequent_topics` (JSONB) — automatycznie aktualizowane po każdym query
  - `preferred_language` — wykrywany z pierwszych interakcji
  - `query_history` — powiązanie z chat_sessions
- System proaktywnie oferuje powiązane informacje na podstawie historii

### 3.6 Kolekcje dokumentów (Foldery/Tagi)

#### Mechanika
- Użytkownik tworzy **foldery** (hierarchiczne) i przypisuje **tagi** (płaskie)
- Przy tworzeniu chatu wybiera folder/tag → retrieval ograniczony do tego podzbioru
- Możliwość łączenia wielu folderów/tagów w jednym chacie
- Przykład: Adwokat wybiera folder "Sprawa Kowalski" (3 dokumenty) + tag "orzecznictwo" (15 dokumentów) → RAG szuka w tych 18 dokumentach

#### Tabele DB
```sql
-- Foldery (hierarchiczne, tree structure)
folders (id, name, parent_id, user_id, created_at)

-- Tagi
tags (id, name, color, user_id)

-- Relacje
document_folders (document_id, folder_id)
document_tags (document_id, tag_id)

-- Kontekst chatu
chat_context (chat_id, folder_id, tag_id)  -- wiele wierszy per chat
```

### 3.7 Duplikaty dokumentów

- **Hash-based detection**: SHA-256 hash pliku przy uploadzie
- Jeśli duplikat wykryty → UI pokazuje dialog:
  - "Ten dokument już istnieje w systemie (dodany DD.MM.YYYY). Co chcesz zrobić?"
  - Opcje: **Zachowaj oba** | **Zastąp istniejący** | **Anuluj**
- Usunięcie dokumentu = usunięcie wszystkich jego chunków z pgvector (delete + vacuum)

### 3.8 Web Crawling (mdream)

- **mdream** (`harlanzw/mdream` Docker image) — lekki crawler + HTML→Markdown konwerter
- Pakiet `@mdream/crawl` — crawluje strony i generuje czyste pliki `.md` zoptymalizowane pod LLM
- Obsługa JavaScript/SPA via driver Playwright
- ~50% mniej tokenów niż standardowe konwertery HTML→text
- Generuje: `llms.txt` (skonsolidowany) + osobne `.md` per strona
- Użytkownik podaje URL + głębokość crawlowania (1-5 poziomów)
- Crawlowane strony konwertowane do markdown → chunking → embedding → tagi
- Brak automatycznego re-crawlowania (on-demand)

---

## 4. Document Lifecycle

### Upload → Przetwarzanie → Indeksowanie
```
1. Upload (UI/API/watch folder)
2. Dedup check (SHA-256)
3. Parsing (Unstructured.io / OCR / Whisper)
4. Chunking (document-aware)
5. Embedding (model z benchmarku, via Ollama na Mac Studio)
6. Storage (pgvector + metadata w PostgreSQL)
7. Confirmation (status w UI, webhook opcjonalnie)
```

### Aktualizacja dokumentu
- **Usuń + re-indeksuj**: usunięcie wszystkich chunków starego dokumentu, przetworzenie nowej wersji od zera
- Brak in-place update (ograniczenie pgvector)

### Usunięcie dokumentu
- Kaskadowe usunięcie: dokument → chunki → embeddingi → relacje z folderami/tagami

---

## 5. Walidacja i Quality Assurance

### LLM-as-Judge
- Dedykowany LLM (mniejszy model, np. Qwen3 0.6B) ocenia każdą odpowiedź
- Metryki:
  - **Groundedness**: czy odpowiedź wynika bezpośrednio z dostarczonych fragmentów (0.0-1.0)
  - **Completeness**: czy odpowiedź uwzględnia wszystkie relevantne fragmenty (0.0-1.0)
  - **Relevance**: czy odpowiedź jest na temat pytania (0.0-1.0)
- Wyniki zapisywane w LangFuse trace
- Jeśli groundedness < 0.7 → odpowiedź oznaczona ostrzeżeniem w UI

### AI Agent Ranker (background)
- Agent działający w tle, analizujący jakość retrievalu
- Periodycznie testuje sample queries i mierzy drift jakości
- Alert jeśli jakość spada poniżej threshold
- Sugeruje re-embedding lub zmianę modelu embeddingowego

### LangFuse (self-hosted)
- Pełny tracing pipeline: query → retrieval → reranking → generation → validation
- Dashboard z metrykami: latencja, token usage, groundedness over time
- Docker serwis w `docker-compose-infra.yml`

---

## 6. API Design (REST)

### Endpoints

#### Documents
```
POST   /api/v1/documents/upload          — Upload dokumentu (multipart)
GET    /api/v1/documents                  — Lista dokumentów (filtry: folder, tag, type)
GET    /api/v1/documents/{id}             — Szczegóły dokumentu
DELETE /api/v1/documents/{id}             — Usuń dokument + re-index
GET    /api/v1/documents/{id}/chunks      — Lista chunków dokumentu
POST   /api/v1/documents/crawl            — Inicjuj web crawl (URL + depth)
GET    /api/v1/documents/tasks/{task_id}  — Status przetwarzania
```

#### Chat / Query
```
POST   /api/v1/chat                       — Nowy chat (+ opcjonalny context: folders/tags)
POST   /api/v1/chat/{id}/query            — Zadaj pytanie (SSE streaming response)
GET    /api/v1/chat/{id}/history          — Historia rozmowy
DELETE /api/v1/chat/{id}                  — Usuń chat
```

#### Kolekcje
```
POST   /api/v1/folders                    — Utwórz folder
GET    /api/v1/folders                    — Lista folderów (tree)
PUT    /api/v1/folders/{id}               — Edytuj folder
DELETE /api/v1/folders/{id}               — Usuń folder

POST   /api/v1/tags                       — Utwórz tag
GET    /api/v1/tags                       — Lista tagów
DELETE /api/v1/tags/{id}                  — Usuń tag

POST   /api/v1/documents/{id}/folders     — Przypisz dokument do folderu
POST   /api/v1/documents/{id}/tags        — Dodaj tag do dokumentu
```

#### Users / Profile
```
POST   /api/v1/auth/login                — Logowanie (basic auth → JWT session)
GET    /api/v1/users/me                   — Profil użytkownika
GET    /api/v1/users/me/interests         — Historia zainteresowań
```

#### System
```
GET    /api/v1/health                     — Health check
GET    /api/v1/stats                      — Statystyki (ilość dokumentów, chunków, zapytań)
GET    /api/v1/benchmark/status           — Status benchmarku embeddingów
POST   /api/v1/benchmark/run              — Uruchom benchmark
```

### Autentykacja
- Basic auth (user/pass) przy logowaniu → JWT token w response
- JWT token w headerze `Authorization: Bearer <token>` dla kolejnych requestów
- Lista userów w bazie danych (tabela `users`)
- Brak rejestracji — admin tworzy userów ręcznie

### OpenAPI/Swagger
- Auto-generowana dokumentacja na `/docs` (FastAPI built-in)

---

## 7. Frontend (React + TypeScript)

### Layout
```
┌─────────────────────────────────────────────────────────────┐
│  Sidebar (250px)              │  Main Area                  │
│  ┌─────────────────────────┐  │  ┌─────────────────────────┐│
│  │ 📁 Foldery (tree)       │  │  │  Chat Area              ││
│  │  ├─ Sprawa Kowalski     │  │  │                         ││
│  │  ├─ Dokumentacja tech.  │  │  │  [Q] Pytanie user       ││
│  │  └─ Analizy rynkowe     │  │  │  [A] Odpowiedź + [1][2] ││
│  │                         │  │  │                         ││
│  │ 🏷️ Tagi                 │  │  │  [Q] Follow-up          ││
│  │  prawo, finanse, tech   │  │  │  [A] Odpowiedź + [3]    ││
│  │                         │  │  │                         ││
│  │ 💬 Historia chatów      │  │  │  ┌───────────────────┐  ││
│  │  Chat 1 (wczoraj)       │  │  │  │ 📝 Input pytania  │  ││
│  │  Chat 2 (dziś)          │  │  │  └───────────────────┘  ││
│  └─────────────────────────┘  │  └─────────────────────────┘│
│                               │                             │
│  ┌─────────────────────────┐  │  ┌─────────────────────────┐│
│  │ ⬆️ Upload area           │  │  │  Sources Panel (fold)   ││
│  │ (drag & drop)           │  │  │  [1] umowa.pdf p.5 §3   ││
│  └─────────────────────────┘  │  │  [2] regulamin.docx p.12││
│                               │  │  [3] akt_notarialny.pdf ││
│                               │  └─────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

### Kluczowe widoki
1. **Chat view** — główny widok z chatem, sources panel, inline cytaty
2. **Documents view** — biblioteka dokumentów z folderami, tagami, statusem przetwarzania
3. **Upload view** — drag-and-drop + URL input do crawlowania + watch folder status
4. **Profile view** — profil użytkownika, historia zainteresowań, preferencje
5. **Admin view** — zarządzanie userami, benchmark status, system stats

### Technologie frontend
- **React 18+** z TypeScript
- **Vite** jako bundler
- **TanStack Query** (React Query) do zarządzania stanem API
- **Tailwind CSS** do stylowania
- **shadcn/ui** jako biblioteka komponentów
- **react-markdown** do renderowania odpowiedzi
- **EventSource** (SSE) do streaming odpowiedzi

---

## 8. Database Schema (PostgreSQL + pgvector)

```sql
-- Rozszerzenia
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Użytkownicy
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(200),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Profile użytkowników
CREATE TABLE user_profiles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    frequent_topics JSONB DEFAULT '{}',
    preferred_language VARCHAR(10) DEFAULT 'auto',
    settings JSONB DEFAULT '{}',
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Dokumenty
CREATE TABLE documents (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    filename VARCHAR(500) NOT NULL,
    original_path TEXT,
    file_type VARCHAR(50) NOT NULL,
    file_hash VARCHAR(64) NOT NULL,           -- SHA-256
    file_size BIGINT,
    page_count INTEGER,
    status VARCHAR(20) DEFAULT 'pending',      -- pending, processing, ready, error
    source_type VARCHAR(20) DEFAULT 'upload',  -- upload, api, watch_folder, web_crawl
    source_url TEXT,                           -- dla web crawl
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP
);

-- Chunki dokumentów
CREATE TABLE document_chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding vector(768),                     -- wymiar zależy od modelu (ustalony po benchmark)
    page_number INTEGER,
    section_title VARCHAR(500),
    chunk_type VARCHAR(50) DEFAULT 'text',     -- text, table, image_ocr, audio_transcript
    token_count INTEGER,
    metadata JSONB DEFAULT '{}',               -- timestamps dla audio, coordinates dla OCR
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indeksy
CREATE INDEX idx_chunks_embedding ON document_chunks
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX idx_chunks_document ON document_chunks(document_id);
CREATE INDEX idx_chunks_content_trgm ON document_chunks USING gin (content gin_trgm_ops);
CREATE INDEX idx_chunks_content_fts ON document_chunks
    USING gin (to_tsvector('simple', content));

-- Foldery (hierarchiczne)
CREATE TABLE folders (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Tagi
CREATE TABLE tags (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    color VARCHAR(7) DEFAULT '#3B82F6',
    user_id INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(name, user_id)
);

-- Relacje dokument ↔ folder/tag
CREATE TABLE document_folders (
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    folder_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
    PRIMARY KEY (document_id, folder_id)
);

CREATE TABLE document_tags (
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    tag_id INTEGER REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (document_id, tag_id)
);

-- Sesje chatowe
CREATE TABLE chat_sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    title VARCHAR(300),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Kontekst chatu (powiązane foldery/tagi)
CREATE TABLE chat_context (
    id SERIAL PRIMARY KEY,
    chat_id INTEGER REFERENCES chat_sessions(id) ON DELETE CASCADE,
    folder_id INTEGER REFERENCES folders(id) ON DELETE SET NULL,
    tag_id INTEGER REFERENCES tags(id) ON DELETE SET NULL
);

-- Wiadomości chatowe
CREATE TABLE chat_messages (
    id SERIAL PRIMARY KEY,
    chat_id INTEGER REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,                 -- user, assistant
    content TEXT NOT NULL,
    sources JSONB,                             -- [{document_id, page, section, chunk_id, confidence}]
    groundedness_score FLOAT,
    completeness_score FLOAT,
    relevance_score FLOAT,
    token_count INTEGER,
    latency_ms INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Processing tasks
CREATE TABLE processing_tasks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    task_type VARCHAR(50) NOT NULL,            -- parse, chunk, embed, ocr, whisper, crawl
    status VARCHAR(20) DEFAULT 'pending',       -- pending, running, completed, failed
    progress FLOAT DEFAULT 0,                   -- 0.0 - 1.0
    error_message TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Benchmark results
CREATE TABLE embedding_benchmarks (
    id SERIAL PRIMARY KEY,
    model_name VARCHAR(200) NOT NULL,
    recall_at_5 FLOAT,
    recall_at_10 FLOAT,
    mrr FLOAT,
    ndcg_at_10 FLOAT,
    avg_latency_ms FLOAT,
    test_set_size INTEGER,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 9. Struktura projektu

```
RAG/
├── docker-compose-infra.yml       # PostgreSQL, Redis, LangFuse
├── docker-compose-app.yml         # FastAPI+Docling, React, Celery, mdream
├── docker-compose-ai.yml          # Ollama, mlx-whisper (Mac Studio)
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                    # FastAPI entry point
│   ├── config.py                  # Pydantic settings (env-based)
│   │
│   ├── api/
│   │   ├── routes/
│   │   │   ├── documents.py       # CRUD dokumentów, upload, crawl
│   │   │   ├── chat.py            # Chat endpoints (SSE streaming)
│   │   │   ├── collections.py     # Foldery, tagi
│   │   │   ├── auth.py            # Login, user management
│   │   │   └── system.py          # Health, stats, benchmark
│   │   ├── deps.py                # Dependencies (DB session, auth)
│   │   └── middleware.py          # CORS, logging, error handling
│   │
│   ├── core/
│   │   ├── database.py            # SQLAlchemy models + pgvector operations
│   │   ├── embeddings.py          # Embedding client (Ollama remote)
│   │   ├── llm.py                 # LLM client (Ollama remote, streaming)
│   │   ├── retriever.py           # Hybrid search (semantic + BM25 + RRF)
│   │   ├── chunker.py             # Document-aware chunking logic
│   │   ├── judge.py               # LLM-as-judge (groundedness, completeness)
│   │   └── rewriter.py            # Query rewriting for conversational context
│   │
│   ├── ingestion/
│   │   ├── parser.py              # Docling integration (PDF, DOCX, PPTX, images)
│   │   ├── ocr.py                 # SmolDocling-256M OCR (lokalne, via Docling)
│   │   ├── whisper.py             # mlx-whisper client (remote, Mac Studio)
│   │   ├── crawler.py             # mdream client (HTML→Markdown crawler)
│   │   └── watcher.py             # Watch folder monitor (watchdog)
│   │
│   ├── tasks/
│   │   ├── celery_app.py          # Celery configuration
│   │   ├── document_tasks.py      # Parse, chunk, embed tasks
│   │   ├── crawl_tasks.py         # Web crawling tasks
│   │   └── benchmark_tasks.py     # Embedding benchmark tasks
│   │
│   └── services/
│       ├── document_service.py    # Document business logic
│       ├── chat_service.py        # Chat + RAG pipeline orchestration
│       ├── collection_service.py  # Folder/tag management
│       ├── profile_service.py     # User profile + interest tracking
│       └── ranker_agent.py        # Background AI ranker/evaluator
│
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   │
│   └── src/
│       ├── App.tsx
│       ├── main.tsx
│       ├── api/                   # API client (fetch + SSE)
│       ├── components/
│       │   ├── chat/              # ChatView, MessageBubble, SourcesPanel
│       │   ├── documents/         # DocumentList, UploadArea, CrawlForm
│       │   ├── collections/       # FolderTree, TagManager
│       │   ├── layout/            # Sidebar, Header, MainLayout
│       │   └── ui/                # shadcn/ui components
│       ├── hooks/                 # useChat, useDocuments, useSSE
│       ├── pages/                 # ChatPage, DocumentsPage, ProfilePage, AdminPage
│       ├── store/                 # Zustand/context state
│       └── types/                 # TypeScript interfaces
│
├── ai-services/                   # Dla Mac Studio
│   └── whisper-server/
│       ├── Dockerfile
│       └── server.py             # FastAPI wrapper dla mlx-whisper
│
├── db-init/
│   └── 01-init-rag.sql           # Schema initialization
│
└── .env.example                   # Template konfiguracji
```

---

## 10. Konfiguracja (.env)

```bash
# === Database ===
RAG_DATABASE_URL=postgresql://rag:ragpass@localhost:5434/rag
RAG_DB_PORT=5434

# === Redis ===
REDIS_URL=redis://localhost:6379/1

# === AI Services (Mac Studio) ===
OLLAMA_URL=http://192.168.x.x:11434        # Ollama na Mac Studio
WHISPER_URL=http://192.168.x.x:8002        # mlx-whisper serwis

# === Document Processing (lokalne) ===
DOCLING_OCR_MODEL=SmolDocling-256M-preview  # OCR model (działa na CPU/GPU laptopa)

# === Models ===
LLM_MODEL=qwen3:latest                     # Model generujący
EMBEDDING_MODEL=TBD                        # Po benchmarku
JUDGE_MODEL=qwen3:0.6b                     # LLM-as-judge (mały, szybki)

# === Chunking ===
CHUNK_SIZE=512
CHUNK_OVERLAP=102
MAX_CHUNK_SIZE=1024

# === Retrieval ===
RETRIEVAL_TOP_K=10
SEMANTIC_WEIGHT=0.7
BM25_WEIGHT=0.3

# === Auth ===
JWT_SECRET=<random-secret>
JWT_EXPIRY_HOURS=24

# === mdream (web crawler) ===
MDREAM_DOCKER_IMAGE=harlanzw/mdream:latest
CRAWL_MAX_DEPTH=3
CRAWL_DRIVER=fetch                         # fetch (domyślny) lub playwright (JS/SPA)

# === LangFuse ===
LANGFUSE_HOST=http://localhost:3001
LANGFUSE_PUBLIC_KEY=<key>
LANGFUSE_SECRET_KEY=<key>

# === Watch Folder ===
WATCH_FOLDER_PATH=/data/watch
WATCH_FOLDER_ENABLED=true

# === Limits ===
MAX_FILE_SIZE_MB=500
MAX_CRAWL_PAGES=100

# === Backup ===
BACKUP_SCHEDULE=0 3 * * *                  # codziennie o 3:00
BACKUP_PATH=/backups
```

---

## 11. Hardware Requirements

### Laptop (minimalne)
- CPU: 4 cores
- RAM: 16GB (SmolDocling-256M + Docling + backend)
- Disk: 50GB+ (dokumenty + pgvector + Redis)
- GPU: opcjonalny (SmolDocling działa na CPU, GPU przyspiesza OCR)
- Sieć: LAN connection do Mac Studio

### Mac Studio M3 (inference server)
- RAM/VRAM: 96GB unified memory
- Ollama: Qwen3 (rozmiar TBD) + embedding model
- mlx-whisper: whisper-large-v3 (~3GB)
- Łącznie: ~25-45GB VRAM zajęte (zależnie od modelu LLM, bez OCR — przeniesiony na laptop)

---

## 12. Backup Strategy

- **pg_dump** regularny (cron, domyślnie codziennie o 3:00)
- Backup zawiera: schema + dane + embeddingi (pgvector)
- Retencja: 7 dni (konfigurowalne)
- Oryginalne pliki przechowywane osobno (volume mount)

---

## 13. Otwarte decyzje (do ustalenia po benchmarku)

1. **Embedding model** — finalny wybór po benchmarku (Qwen 0.6B vs multilingual-e5 vs nomic-embed vs mxbai)
2. **Embedding dimension** — determinuje schema pgvector (`vector(768)` vs `vector(1024)` vs inne)
3. **Qwen3 rozmiar** — 1.7B vs 4B vs 8B vs 14B (zależy od tego ile VRAM zostanie po embeddings + Whisper; więcej VRAM dostępne bo OCR przeniesiony na laptop)
4. **Cross-encoder reranker** — czy dodać osobny reranking step (ms-marco-MiniLM vs bez)
5. **Conversational window** — ile wiadomości trzymać w kontekście (5 vs 10 vs 20)
6. **SmolDocling vs Granite-Docling** — Granite-Docling jest stabilniejszy (mniej pętli), ale nowszy; przetestować oba
