# RAG — Hermes Activity Log

Dziennik diagnostyki i napraw prowadzonych przez Hermesa dla projektu RAG. Każdy wpis = jedna sesja (cron tick / error trigger / user request). Najnowsze na górze.

Konwencja:
- **Trigger**: `cron-30min` | `error-detected` | `user-request`
- **Objaw**: co widać z zewnątrz (user/log)
- **Diagnoza**: root cause + model+latency diagnostyki
- **Akcja**: `proposed` | `auto-fixed` | `awaiting-user`
- **Wynik**: wypełniane po weryfikacji (może być `TBD`)

---

## 2026-04-24 ~14:50 UTC — Stuck YouTube transcription (doc#39)

**Trigger**: user-request (user zauważył na telefonie, że doc utknął na 60%)

**Objaw**:
- Doc#39 „5 Agent Skills do jakościowego programowania z AI — Claude Code LIVE DEMO" (źródło: YouTube)
- `status=processing`, `progress=0.6`, ostatnia aktualizacja 2026-04-24 04:42:40 UTC
- Czas utknięcia w momencie diagnozy: ~10h 10min

**Diagnoza** (Haiku + grep logów rag-worker, ~76s):
- Whisper transcription: ✅ OK (1501 segmentów, 117354 znaków)
- Chunking: ✅ OK (569 chunków, 16/batch → 36 batchy oczekiwanych)
- Embedding batches — **degradacja czasu**:
  - batch 1: 47s
  - batch 2: 47s
  - batch 3: 77s
  - batch 4: 194s
  - batch 5: **timeout** (`httpx.ReadTimeout` po ~300s — `RAG/backend/core/embeddings.py:26`)
- Kontenery zdrowe (rag-worker 808MB/10.5%, postgres, redis — bez restartów)
- **Root cause**: model Ollama `qwen3-embedding:0.6b` degraduje latencję per-batch (prawdopodobnie akumulacja kontekstu / pamięć / single-thread bottleneck) + hardcoded timeout 300s nie pozwala się dokończyć.

**Akcja**: `awaiting-user` (decyzja pending)

Proponowany fix dwuetapowy:
1. **Immediate unstick (safe)** — restart host Ollama (Windows Ollama service), potem reprocess doc#39: `POST /api/documents/39/reprocess`
2. **Root-cause fix (code change)** — `RAG/backend/core/embeddings.py`:
   - timeout `300.0` → `900.0` (lub per-batch dynamic)
   - dorobić retry z exponential backoff dla ReadTimeout
   - per-batch log (`batch i/N, latency=X`) żeby degradacja była widoczna wcześniej
   - opcjonalnie: mniejszy batch_size (16 → 8) jeśli Ollama nie daje rady

**Wynik**: TBD

**Notes / do zapamiętania** (wejdzie do skilla `check-rag.md`):
- Sygnał ostrzegawczy: jeśli kolejny batch embed trwa >2× poprzedniego → flag
- Jeśli stuck >10 min przy `status=processing` → alert na Telegram
- Autofix-safe: restart rag-worker + retry reprocess (idempotent dzięki hash-based dedup w chunks)
- Autofix-NIEsafe: zmiana kodu timeout — zawsze user approval
