# CLAUDE.md — RAG Pipeline

## Project Overview

Document processing pipeline with RAG (Retrieval-Augmented Generation).

- **Full spec**: `RAG.MD`
- **Progress**: `PROGRESS.md` (READ THIS FIRST in new sessions)
- **Stack**: FastAPI backend + PostgreSQL/pgvector + Docling + Celery
- **Docker**: `docker-compose-infra.yml` (DB, Redis) + `docker-compose-app.yml` (app, workers)

## Current Status

- FAZA 0-1: Complete
- FAZA 2: Complete (Docling pipeline working)
- FAZA 3: Next (AI integration — needs Mac Studio)

## Key Patterns

### Docling
- `pip install docling` (includes torch, transformers)
- CPU-only: `pip install torch --extra-index-url https://download.pytorch.org/whl/cpu`
- Usage: `DocumentConverter().convert(path).document.export_to_markdown()`
- Handles: PDF, DOCX, PPTX, HTML, images (OCR), CSV
- System deps: `libgl1`, `libglib2.0-0`

### Celery
- `autodiscover_tasks(["tasks"])` unreliable — use explicit imports: `import tasks.document_tasks`
- Workers need sync DB driver (`psycopg2-binary`), not async (`asyncpg`)

### Auth
- PyJWT: `sub` claim must be **string**, not int
- passlib 1.7.4 + bcrypt 4.x: warning `error reading bcrypt version` — harmless

## Database

- Separate from other projects
- Uses pgvector for embeddings
