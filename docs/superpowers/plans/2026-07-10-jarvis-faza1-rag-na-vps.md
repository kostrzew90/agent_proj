# Jarvis Faza 1 — RAG na VPS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Działający stack RAG na Oracle VPS (dom Jarvisa): czat z historią + upload PDF dostępne z telefonu przez Tailscale, generacja LLM przez darmowe API, embeddingi lokalnie na CPU.

**Architecture:** Istniejący stack RAG (FastAPI + Celery + Postgres/pgvector + Redis + React) przeniesiony na VPS w nowym profilu compose. Generacja/judge/reranker przez istniejącą ścieżkę OpenAI-compatible (`core/openrouter.py`) z nowym parametrem `base_url` wskazującym darmowy endpoint Gemini. Embeddingi przez kontener Ollama (CPU, qwen3-embedding:0.6b) — ten sam model co na laptopie, więc zero zmian schematu (vector(1024)). Dostęp wyłącznie przez tailnet (Oracle firewall zostaje zamknięty publicznie).

**Tech Stack:** Docker Compose, FastAPI, Celery, pgvector/pg16, Redis 7, Ollama (CPU), Gemini OpenAI-compat endpoint, Tailscale.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-10-jarvis-vps-reporter-design.md` (Faza 1)
- VPS: `ubuntu@84.235.174.129`, klucz SSH `C:\ai\ssh-key-2026-05-19.key`, x86_64, 4 vCPU, 15 GB RAM — **działa tam Argus (4 kontenery), NIE wolno go dotykać ani restartować**
- Bez LangFuse i bez Flower na VPS w Fazie 1
- Celery worker: `--concurrency=1` na VPS
- LLM wyłącznie darmowe API (Gemini free primary; awaryjnie OpenRouter przez zmianę env, bez zmian kodu)
- Embeddingi: `qwen3-embedding:0.6b` (1024 dim) — decyzja CPU vs API rozstrzygana testem wydajności w Task 4; API tylko jeśli CPU > 30 s/dokument testowy
- Whisper na VPS: `WHISPER_MODEL_SIZE=small` (ochrona RAM)
- Wszystkie komendy lokalne wykonywane na Windows w Git Bash; `python` (3.11) jest na hoście
- Deploy NIE nadpisuje `~/argus/` na VPS; RAG ląduje w `~/rag/`
- Praca na branchu `feat/argus-phase1` (bez zmiany brancha), commity tylko plików wymienionych w taskach

---

### Task 1: Porządek w RAG/ — commit zaległej pracy

**Files:**
- Modify: `.gitignore` (root repo)
- Commit: wszystkie zmodyfikowane i nieśledzone pliki pod `RAG/` (lista niżej)

**Interfaces:**
- Consumes: —
- Produces: czysty `git status` dla `RAG/` — warunek startu deployu (deploy kopiuje działający, wersjonowany stan)

- [ ] **Step 1: Wyklucz artefakty generowane**

Dopisz na końcu `.gitignore` w rocie repo:

```gitignore
RAG/graphify-out/
```

- [ ] **Step 2: Obejrzyj zmiany zanim je zacommitujesz**

Run: `git -C "C:/Users/DAMA/Documents/docker/n8n" diff --stat -- RAG/ && git status --porcelain RAG/`
Expected: lista ~15 zmodyfikowanych + ~15 nieśledzonych plików; ŻADEN plik spoza `RAG/` (poza `.gitignore` z Step 1). Jeśli w diffie widać sekrety (klucze API w plikach) — STOP, zgłoś do review zamiast commitować.

- [ ] **Step 3: Commit 1 — backend (zmodyfikowane + nowe moduły core/api/tasks/services)**

```bash
cd "C:/Users/DAMA/Documents/docker/n8n"
git add RAG/PROGRESS.md RAG/HERMES-LOG.md RAG/backend/
git commit -m "feat(rag): zaległy stan backendu — chat SSE, retriever, judge, openrouter, rate limit, benchmark"
```

- [ ] **Step 4: Commit 2 — frontend + skrypty + gitignore**

```bash
git add RAG/frontend/ RAG/scripts/ .gitignore
git commit -m "feat(rag): frontend React (czat, upload, auth) + skrypty backup/restore"
```

- [ ] **Step 5: Zweryfikuj czystość**

Run: `git status --porcelain RAG/`
Expected: puste wyjście (ewentualnie tylko pliki ignorowane niewidoczne). `RAG/graphify-out/` nie jest w repo.

---

### Task 2: `base_url` w OpenRouterClient (Gemini OpenAI-compat)

**Files:**
- Modify: `RAG/backend/core/openrouter.py`
- Modify: `RAG/backend/config.py:43-46` (sekcja OpenRouter w `AISettings`)
- Modify: `RAG/backend/services/chat_service.py:28-34`, `RAG/backend/core/judge.py:69-73`, `RAG/backend/core/llm_reranker.py:160-164` (przekazanie `base_url`)
- Test: `RAG/backend/tests/test_openrouter_base_url.py` (nowy)

**Interfaces:**
- Consumes: `OpenRouterClient(api_key, model, timeout)` z `core/openrouter.py` (istniejący)
- Produces: `OpenRouterClient(api_key, model, timeout=120.0, base_url: str | None = None)` — `base_url=None` zachowuje dotychczasowe `https://openrouter.ai/api/v1`; `settings.ai.openrouter_base_url: str = ""` (env `OPENROUTER_BASE_URL`). Task 3 ustawia env na `https://generativelanguage.googleapis.com/v1beta/openai` z kluczem Gemini.

- [ ] **Step 1: Napisz failing test**

Utwórz `RAG/backend/tests/test_openrouter_base_url.py`:

```python
"""OpenRouterClient must accept a custom base_url (Gemini OpenAI-compat endpoint)."""
from core.openrouter import OpenRouterClient, OPENROUTER_BASE

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"


def test_default_base_url_unchanged():
    client = OpenRouterClient(api_key="k", model="m")
    assert str(client._client.base_url).rstrip("/") == OPENROUTER_BASE.rstrip("/")


def test_custom_base_url():
    client = OpenRouterClient(api_key="k", model="m", base_url=GEMINI_BASE)
    assert str(client._client.base_url).rstrip("/") == GEMINI_BASE


def test_empty_base_url_falls_back_to_default():
    client = OpenRouterClient(api_key="k", model="m", base_url="")
    assert str(client._client.base_url).rstrip("/") == OPENROUTER_BASE.rstrip("/")
```

- [ ] **Step 2: Uruchom test — ma paść**

Run: `cd "C:/Users/DAMA/Documents/docker/n8n/RAG/backend" && python -m pytest tests/test_openrouter_base_url.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'base_url'`

- [ ] **Step 3: Implementacja w `core/openrouter.py`**

W `__init__` (linie 24-40) dodaj parametr i użyj go:

```python
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: float = 120.0,
        base_url: str | None = None,
    ):
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=(base_url or OPENROUTER_BASE),
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "http://localhost:3003",
                "X-Title": "RAG System",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
```

- [ ] **Step 4: Config — nowe pole w `AISettings`**

W `RAG/backend/config.py` po linii `openrouter_judge_model...` (46) dodaj:

```python
    openrouter_base_url: str = ""  # puste = openrouter.ai; np. Gemini OpenAI-compat endpoint
```

- [ ] **Step 5: Przekaż `base_url` w trzech miejscach użycia**

W `services/chat_service.py`, `core/judge.py`, `core/llm_reranker.py` — do każdego wywołania `OpenRouterClient(...)` dopisz argument (przykład z chat_service, analogicznie w dwóch pozostałych):

```python
            self.llm = OpenRouterClient(
                api_key=settings.ai.openrouter_api_key,
                model=settings.ai.openrouter_model,
                base_url=settings.ai.openrouter_base_url or None,
            )
```

- [ ] **Step 6: Testy — nowy i istniejące**

Run: `cd "C:/Users/DAMA/Documents/docker/n8n/RAG/backend" && python -m pytest tests/test_openrouter_base_url.py tests/test_llm_reranker.py -v`
Expected: nowe 3 testy PASS; test_llm_reranker bez nowych regresji względem stanu sprzed zmiany (uruchom przed i po, porównaj).

- [ ] **Step 7: Commit**

```bash
cd "C:/Users/DAMA/Documents/docker/n8n"
git add RAG/backend/core/openrouter.py RAG/backend/config.py RAG/backend/services/chat_service.py RAG/backend/core/judge.py RAG/backend/core/llm_reranker.py RAG/backend/tests/test_openrouter_base_url.py
git commit -m "feat(rag): configurable base_url w OpenRouterClient (Gemini OpenAI-compat)"
```

---

### Task 3: Profil VPS — `docker-compose.vps.yml` + `.env.vps.example`

**Files:**
- Create: `RAG/docker-compose.vps.yml`
- Create: `RAG/.env.vps.example`

**Interfaces:**
- Consumes: obrazy/Dockerfile z `RAG/backend/` i `RAG/frontend/`, schemat z `RAG/db-init/`
- Produces: jeden plik compose uruchamiający całość na VPS komendą `docker compose -f docker-compose.vps.yml up -d`; nazwy kontenerów `rag-*` jak dotychczas; Ollama pod `http://rag-ollama:11434`

- [ ] **Step 1: Utwórz `RAG/docker-compose.vps.yml`**

```yaml
# RAG na VPS (Jarvis Faza 1) — bez LangFuse, bez Flower, worker x1, Ollama CPU (embeddingi)
services:
  rag-postgres:
    image: pgvector/pgvector:pg16
    container_name: rag-postgres
    restart: unless-stopped
    ports:
      - "127.0.0.1:5434:5432"
    environment:
      POSTGRES_USER: ${RAG_DB_USER:-rag}
      POSTGRES_PASSWORD: ${RAG_DB_PASSWORD:-ragpass}
      POSTGRES_DB: ${RAG_DB_NAME:-rag}
    volumes:
      - rag-postgres-data:/var/lib/postgresql/data
      - ./db-init:/docker-entrypoint-initdb.d
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${RAG_DB_USER:-rag} -d ${RAG_DB_NAME:-rag}"]
      interval: 10s
      timeout: 5s
      retries: 5

  rag-redis:
    image: redis:7-alpine
    container_name: rag-redis
    restart: unless-stopped
    volumes:
      - rag-redis-data:/data
    command: redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  rag-ollama:
    image: ollama/ollama:latest
    container_name: rag-ollama
    restart: unless-stopped
    volumes:
      - rag-ollama-data:/root/.ollama
    deploy:
      resources:
        limits:
          memory: 3g

  rag-api:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: rag-api
    restart: unless-stopped
    ports:
      - "8000:8000"
    env_file:
      - .env
    environment:
      RAG_DB_HOST: rag-postgres
      RAG_DB_PORT: 5432
      REDIS_URL: redis://rag-redis:6379/0
      OLLAMA_URL: http://rag-ollama:11434
    volumes:
      - rag-uploads:/data/uploads
      - rag-watch:/data/watch
    depends_on:
      rag-postgres:
        condition: service_healthy
      rag-redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')"]
      interval: 30s
      timeout: 10s
      retries: 3

  rag-worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: rag-worker
    restart: unless-stopped
    command: celery -A tasks.celery_app worker --loglevel=info --concurrency=1 -Q default,documents,crawl
    env_file:
      - .env
    environment:
      RAG_DB_HOST: rag-postgres
      RAG_DB_PORT: 5432
      REDIS_URL: redis://rag-redis:6379/0
      OLLAMA_URL: http://rag-ollama:11434
      WHISPER_MODEL_SIZE: small
      WHISPER_THREADS: "2"
    volumes:
      - rag-uploads:/data/uploads
      - rag-watch:/data/watch
    depends_on:
      rag-postgres:
        condition: service_healthy
      rag-redis:
        condition: service_healthy

  rag-frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: rag-frontend
    restart: unless-stopped
    ports:
      - "3003:80"
    depends_on:
      rag-api:
        condition: service_healthy

volumes:
  rag-postgres-data:
  rag-redis-data:
  rag-ollama-data:
  rag-uploads:
  rag-watch:
```

- [ ] **Step 2: Utwórz `RAG/.env.vps.example`**

```bash
# === RAG na VPS (Jarvis Faza 1) — skopiuj do .env na VPS i uzupełnij ===
RAG_DB_USER=rag
RAG_DB_PASSWORD=ZMIEN-MNIE-silne-haslo
RAG_DB_NAME=rag

JWT_SECRET=ZMIEN-MNIE-losowe-32-znaki-minimum

# LLM przez Gemini OpenAI-compat (darmowy tier); klucz ten sam co w ~/argus/.env
OPENROUTER_API_KEY=GEMINI_API_KEY_TUTAJ
OPENROUTER_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
OPENROUTER_MODEL=gemini-2.5-flash
OPENROUTER_JUDGE_MODEL=gemini-2.5-flash

# Awaryjnie (429 na Gemini): odkomentuj i wstaw klucz OpenRouter, zakomentuj 4 linie wyżej
# OPENROUTER_API_KEY=sk-or-...
# OPENROUTER_BASE_URL=
# OPENROUTER_MODEL=google/gemma-4-31b-it:free
# OPENROUTER_JUDGE_MODEL=google/gemma-4-31b-it:free

# Embeddingi — kontener rag-ollama (ustawiane też w compose, tu dla jasności)
EMBEDDING_MODEL=qwen3-embedding:0.6b
EMBEDDING_DIMENSION=1024

# Whisper API (opcjonalnie, transkrypcje audio)
GROQ_API_KEY=
```

- [ ] **Step 3: Walidacja składni compose**

Run: `cd "C:/Users/DAMA/Documents/docker/n8n/RAG" && cp .env.vps.example .env.vps.tmp && docker compose -f docker-compose.vps.yml --env-file .env.vps.tmp config >/dev/null && rm .env.vps.tmp && echo OK`
Expected: `OK` (bez błędów parsowania).

- [ ] **Step 4: Commit**

```bash
cd "C:/Users/DAMA/Documents/docker/n8n"
git add RAG/docker-compose.vps.yml RAG/.env.vps.example
git commit -m "feat(rag): profil compose na VPS (Ollama CPU embeddingi, bez LangFuse/Flower)"
```

---

### Task 4: Deploy na VPS + smoke testy

**Files:**
- brak zmian w repo (operacje na VPS); wynik testu wydajności embeddingów dopisz do `RAG/PROGRESS.md` (sekcja "Log sesji") i zacommituj

**Interfaces:**
- Consumes: Task 1-3 (czyste repo, base_url, compose VPS)
- Produces: działający stack `rag-*` na VPS w `~/rag/`; health OK; admin login działa; embeddingi zmierzone

- [ ] **Step 1: Spakuj i wyślij RAG na VPS (bez artefaktów)**

Run (Git Bash):
```bash
cd "C:/Users/DAMA/Documents/docker/n8n"
tar czf /tmp/rag-deploy.tgz --exclude='node_modules' --exclude='graphify-out' --exclude='.env' --exclude='__pycache__' --exclude='*.pyc' RAG/
scp -i "C:/ai/ssh-key-2026-05-19.key" /tmp/rag-deploy.tgz ubuntu@84.235.174.129:~/rag-deploy.tgz
ssh -i "C:/ai/ssh-key-2026-05-19.key" ubuntu@84.235.174.129 "mkdir -p ~/rag && tar xzf ~/rag-deploy.tgz -C ~/rag --strip-components=1 && rm ~/rag-deploy.tgz && ls ~/rag"
```
Expected: listing zawiera `backend frontend db-init docker-compose.vps.yml .env.vps.example`.

- [ ] **Step 2: Przygotuj .env na VPS (klucz Gemini z Argusa)**

Run:
```bash
ssh -i "C:/ai/ssh-key-2026-05-19.key" ubuntu@84.235.174.129 '
  cd ~/rag && cp .env.vps.example .env
  GK=$(grep "^GEMINI_API_KEY=" ~/argus/.env | cut -d= -f2)
  sed -i "s|OPENROUTER_API_KEY=GEMINI_API_KEY_TUTAJ|OPENROUTER_API_KEY=$GK|" .env
  sed -i "s|RAG_DB_PASSWORD=ZMIEN-MNIE-silne-haslo|RAG_DB_PASSWORD=$(openssl rand -hex 16)|" .env
  sed -i "s|JWT_SECRET=ZMIEN-MNIE-losowe-32-znaki-minimum|JWT_SECRET=$(openssl rand -hex 32)|" .env
  grep -c "TUTAJ\|ZMIEN-MNIE" .env || true'
```
Expected: ostatnia linia `0` (wszystkie placeholdery podmienione). NIE wypisuj zawartości `.env` do logu.

- [ ] **Step 3: Build i start (bez dotykania Argusa)**

Run:
```bash
ssh -i "C:/ai/ssh-key-2026-05-19.key" ubuntu@84.235.174.129 'cd ~/rag && docker compose -f docker-compose.vps.yml up -d --build 2>&1 | tail -5 && docker compose -f docker-compose.vps.yml ps'
```
Expected: 6 kontenerów `rag-*` w stanie Up/healthy (postgres, redis, ollama, api, worker, frontend). Build potrwa (docling+torch ~10 min).

- [ ] **Step 4: Pobierz model embeddingowy do Ollamy**

Run: `ssh -i "C:/ai/ssh-key-2026-05-19.key" ubuntu@84.235.174.129 'docker exec rag-ollama ollama pull qwen3-embedding:0.6b && docker exec rag-ollama ollama list'`
Expected: `qwen3-embedding:0.6b` na liście.

- [ ] **Step 5: Health + login admina**

Run:
```bash
ssh -i "C:/ai/ssh-key-2026-05-19.key" ubuntu@84.235.174.129 '
  curl -s http://localhost:8000/api/v1/health
  echo
  grep -ri "admin" ~/rag/db-init/ | head -3'
```
Expected: health zwraca JSON ze statusem ok; grep pokazuje seed admina w db-init (login/hasło z seedu). Jeśli seedu BRAK — utwórz użytkownika:
```bash
ssh -i "C:/ai/ssh-key-2026-05-19.key" ubuntu@84.235.174.129 'docker exec rag-api python -c "
from passlib.hash import bcrypt
print(bcrypt.hash(\"PODANE-PRZEZ-USERA-HASLO\"))"'
# następnie INSERT do tabeli users przez: docker exec rag-postgres psql -U rag -d rag
```
Potem test logowania: `curl -s -X POST http://localhost:8000/api/v1/auth/login -H "Content-Type: application/json" -d '{"username":"admin","password":"..."}'` → oczekiwany token JWT.

- [ ] **Step 6: Test wydajności embeddingów (bramka CPU vs API)**

Run:
```bash
ssh -i "C:/ai/ssh-key-2026-05-19.key" ubuntu@84.235.174.129 'time curl -s http://localhost:11434/api/embeddings -d "{\"model\":\"qwen3-embedding:0.6b\",\"prompt\":\"To jest testowy akapit o długości typowego chunka dokumentu. Zawiera kilka zdań po polsku, żeby zmierzyć realny czas embeddingu na CPU VPS.\"}" -o /dev/null --write-out "%{http_code}"' 
```
UWAGA: port 11434 nie jest wystawiony z kontenera — wykonaj przez `docker exec rag-ollama` lub dodaj tymczasowo `docker exec rag-api python -c` używające `core/embeddings.py`. Kryterium: pojedynczy chunk < 2 s, dokument testowy 10 chunków < 30 s łącznie. Jeśli przekroczone → odnotuj w PROGRESS.md i zgłoś decyzję o API embeddings do review (zmiana modelu = re-embedding, NIE rób samowolnie).

- [ ] **Step 7: E2E czatu przez API (dokument + pytanie)**

Run (z tokenem JWT ze Step 5):
```bash
ssh -i "C:/ai/ssh-key-2026-05-19.key" ubuntu@84.235.174.129 '
  TOKEN=<JWT>
  printf "Jarvis test: stolica Polski to Warszawa. Dokument testowy Fazy 1." > /tmp/test.txt
  curl -s -X POST http://localhost:8000/api/v1/documents/upload -H "Authorization: Bearer $TOKEN" -F "file=@/tmp/test.txt"
  sleep 20
  curl -s -N -X POST http://localhost:8000/api/v1/chat -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"message\":\"Co jest stolicą Polski według dokumentu testowego?\"}" | head -20'
```
Expected: upload zwraca id dokumentu; po ~20 s status ready; czat streamuje odpowiedź zawierającą "Warszawa" (generacja przez Gemini — sprawdź w logach `docker logs rag-api --tail 20`, że NIE ma prób łączenia z host.docker.internal).

- [ ] **Step 8: RAM sanity — Argus nietknięty**

Run: `ssh -i "C:/ai/ssh-key-2026-05-19.key" ubuntu@84.235.174.129 'free -h && docker ps --format "{{.Names}}\t{{.Status}}" | sort'`
Expected: wszystkie kontenery `argus-*` Up (bez restartu — sprawdź uptime), dostępne ≥ 2 GB wolnego RAM. Jeśli mniej — zgłoś do review przed kontynuacją.

- [ ] **Step 9: Zapisz wyniki i commit**

Dopisz do `RAG/PROGRESS.md` (Log sesji) wynik: czas buildu, czas embeddingu/chunk, wynik E2E, wolny RAM. Potem:
```bash
cd "C:/Users/DAMA/Documents/docker/n8n"
git add RAG/PROGRESS.md
git commit -m "docs(rag): log deployu VPS — smoke E2E + wydajność embeddingów CPU"
```

---

### Task 5: Tailscale na VPS + dostęp z telefonu

**Files:**
- brak zmian w repo (operacje na VPS + akcja usera)

**Interfaces:**
- Consumes: działający stack z Task 4
- Produces: URL `http://<tailnet-hostname>:3003` działający na telefonie usera

- [ ] **Step 1: Instalacja Tailscale na VPS**

Run: `ssh -i "C:/ai/ssh-key-2026-05-19.key" ubuntu@84.235.174.129 'curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale version'`
Expected: wersja tailscale wypisana bez błędów.

- [ ] **Step 2: Dołączenie do tailnetu (AKCJA USERA)**

Run: `ssh -i "C:/ai/ssh-key-2026-05-19.key" ubuntu@84.235.174.129 'sudo tailscale up --hostname=jarvis-vps 2>&1 | head -5'`
Expected: URL autoryzacyjny `https://login.tailscale.com/a/...` — **przekaż go userowi** (kliknie z telefonu, konto tailnet to to samo co Mac Studio). Czekaj na potwierdzenie usera, potem:
`ssh ... 'tailscale status | head -5'` → `jarvis-vps` widoczny z adresem 100.x.x.x.

- [ ] **Step 3: Weryfikacja dostępu przez tailnet**

Run: `ssh -i "C:/ai/ssh-key-2026-05-19.key" ubuntu@84.235.174.129 'curl -s -o /dev/null -w "%{http_code}" http://$(tailscale ip -4):3003 && echo && curl -s -o /dev/null -w "%{http_code}" http://$(tailscale ip -4):8000/api/v1/health'`
Expected: `200` dla obu (frontend i API osiągalne po adresie tailnetowym).

- [ ] **Step 4: Publiczny firewall sanity**

Run: `ssh -i "C:/ai/ssh-key-2026-05-19.key" ubuntu@84.235.174.129 'sudo iptables -L INPUT -n | head -20'` oraz z laptopa: `curl -s -m 5 -o /dev/null -w "%{http_code}" http://84.235.174.129:3003 || echo BLOCKED`
Expected: z publicznego internetu `BLOCKED`/timeout (Oracle Security List zamknięta — porty 3003/8000 NIE są otwarte publicznie); przez tailnet działa.

- [ ] **Step 5: E2E z telefonu (AKCJA USERA — kryterium sukcesu Fazy 1 ze speca)**

User na telefonie (z appką Tailscale włączoną): otwiera `http://jarvis-vps:3003` (lub `http://100.x.x.x:3003`), loguje się, zadaje pytanie w czacie (historia widoczna), wgrywa PDF i pyta o niego. Zbierz potwierdzenie usera + ewentualne problemy (wolna generacja, błędy UI na mobile).

- [ ] **Step 6: Zamknięcie Fazy 1 w dokumentach**

Dopisz do `RAG/PROGRESS.md`: "Faza 1 Jarvisa (spec 2026-07-10) — RAG działa na VPS, dostęp Tailscale, E2E z telefonu potwierdzone przez usera [data]". Commit:
```bash
cd "C:/Users/DAMA/Documents/docker/n8n"
git add RAG/PROGRESS.md
git commit -m "docs(rag): Faza 1 Jarvisa zamknięta — E2E z telefonu potwierdzone"
```

---

## Poza planem (pilnuj scope)

- Żadnych zmian w Argusie (nawet "przy okazji")
- Żadnych tabel/kolektorów Jarvisa (to Faza 2 — osobny plan)
- Żadnego LangFuse, Flower, multi-tenanta, publicznego wystawiania portów
- Decyzja API-embeddings tylko przez review (re-embedding = zmiana wymiaru = migracja)
