# CLAUDE.md — RAG Pipeline

## Project Overview

Document processing pipeline with RAG (Retrieval-Augmented Generation).

- **Full spec**: `RAG.MD`
- **Progress**: `PROGRESS.md` (READ THIS FIRST in new sessions)
- **Stack**: FastAPI backend + PostgreSQL/pgvector + Docling + Celery
- **Docker**: `docker-compose-infra.yml` (DB, Redis) + `docker-compose-app.yml` (app, workers)

## Current Status

- FAZA 0-6: Complete (full stack working)
- FAZA 4.7-4.8: Complete (profile tracking + quality ranker)
- FAZA 7.1-7.3: Complete (benchmark: R@5=0.97, MRR=0.95, nDCG=0.95)
- FAZA 8.1-8.3: Complete (backup, error handling, rate limiting)
- Remaining: 7.4-7.5 (model comparison, LangFuse) + 8.4 (docs)

## AI Models (Ollama localhost:11434)

- **Embedding**: `qwen3-embedding:0.6b` (1024 dimensions)
- **LLM**: `qwen3:4b` (generation, streaming)
- **Judge**: `qwen3:1.7b` (groundedness validation)
- Docker access: `host.docker.internal:11434`

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

## Agentic Patterns

Inspiracja: [github.com/pguso/ai-agents-from-scratch](https://github.com/pguso/ai-agents-from-scratch) (MIT, JS — patterns translated to Python).

### Zaimplementowane

**Tree of Thought scoring** — `core/llm_reranker.py`
- LLM ocenia każdy chunk niezależnie na 3 osiach (relevance + specificity + coverage)
- Reranking z hybrid merge: 0.7 × LLM + 0.3 × RRF (stabilność z embedding/BM25)
- Diversity cap (max 2 chunks per section) — odpowiednik "branch pruning"
- Pydantic validation LLM output (rejects out-of-range scores)
- Graceful fallback: LLM error → RRF order, error logged

**Chain of Thought reasoning** — `core/judge.py`
- LLM-as-judge ocenia odpowiedź na 3 wymiarach (groundedness/completeness/relevance)
- `<think>` blocks z qwen3 stripowane przed JSON parse
- Audytowalny ślad: każdy wymiar oceniony niezależnie, zapisany w `ChatMessage` table

**Hybrid retrieval (RRF)** — `core/retriever.py`
- pgvector (semantic, 0.7) + BM25 tsvector (0.3) → RRF fusion (k=60)
- 30 kandydatów przed fuzją → top 10 po fuzji → top 5 po reranku → LLM

### Pipeline end-to-end (Production)

```
Query → Query Rewriter (CoT) → Hybrid Retrieval (semantic + BM25 + RRF)
      → LLM Reranker (Tree of Thought scoring + diversity)
      → Generation (qwen3:4b / Gemini Flash)
      → LLM Judge (Chain of Thought scoring)
      → LangFuse trace
```

### Potencjalne rozszerzenia (v2)

| Pattern z repo | Możliwe zastosowanie w RAG |
|---|---|
| **ReAct** | Self-correction loop — jeśli judge score niski, regeneruj z innym promptem |
| **Atom of Thought** | Multi-hop reasoning — rozbij złożone pytanie na atomic subqueries |
| **Graph of Thought** | Multi-source fusion — łącz wyniki z różnych folderów/kolekcji z conflict resolution |
| **Cross-encoder reranker** | BGE reranker GPU jako 2-stage rerank przed LLM (szybsze, bardziej deterministyczne) |

Szczegóły planów: `docs/superpowers/plans/` — patrz `2026-05-25-rag-llm-reranker.md` sekcja "Deferred to v2".

### Zasada

LLM nigdy nie nadpisuje całkowicie deterministycznego scoringu — zawsze hybrid merge z RRF/embedding. Małe modele (qwen3:1.7b) mają losowe preference; RRF daje stabilność. Każdy LLM call jest:
1. Walidowany przez pydantic
2. Loggowany (latency, fallback rate)
3. Z graceful fallback do deterministycznego baseline

## Database

- Separate from other projects
- Uses pgvector for embeddings
