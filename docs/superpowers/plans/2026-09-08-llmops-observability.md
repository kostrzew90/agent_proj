# LLMOps Observability (Etap 1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Każde wywołanie LLM z siedmiu projektów ląduje w jednej tabeli, koszt liczy się z jednego wersjonowanego cennika, a Grafana pokazuje koszt/tokeny/błędy w jednym dashboardzie.

**Architecture:** Nowy stack `llmops/` na Contabo VPS (Postgres + kolektor FastAPI). Projekty wysyłają fire-and-forget `POST /v1/calls` przez wendorowany moduł `llmops_client` — nie znają schematu bazy ani hasła. Koszt nie jest zapisywany, tylko wyliczany widokiem `v_llm_calls_costed` z tabeli `model_pricing`. Dashboard dokładany do istniejącej `argus-grafana`.

**Tech Stack:** Python 3.11, FastAPI, psycopg2-binary, PostgreSQL 16, pytest, Docker Compose, Grafana (istniejąca instancja).

**Spec:** `docs/superpowers/specs/2026-09-08-llmops-observability-design.md`

## Global Constraints

- **Telemetria nigdy nie wywraca wywołania LLM.** Każde wywołanie klienta w kodzie projektu jest opakowane w `try/except Exception: pass`, a sam klient dodatkowo nie podnosi wyjątków wewnętrznie.
- **Zero treści.** Do `llm_calls` nie trafia prompt, odpowiedź ani kontekst — tylko metadane. Kolektor odrzuca ładunki zawierające pola `prompt`, `response`, `input`, `output` (HTTP 422).
- **Porty bindowane do konkretnego IP**, nigdy `0.0.0.0` — Docker omija ufw na tym hoście. Wzorzec z repo: `"${TAILSCALE_IP:-127.0.0.1}:PORT:PORT"`.
- **Brak `LLMOPS_URL` w env → klient jest no-op.** Ten sam wzorzec, co `RAG/backend/core/langfuse_client.py`.
- **Nic nie jest usuwane.** Cztery istniejące mechanizmy kosztowe (RAG, Argus, llm-proxy, kontekst-ai) zostają nietknięte; nowa telemetria jest dopisywana obok.
- **Zmiany chirurgiczne w cudzych projektach.** W siedmiu repo dotykamy wyłącznie linii wymienionych w zadaniu. Żadnego refaktoru, formatowania ani „ulepszania" sąsiedniego kodu.
- Platforma: Windows 11 + Docker Desktop lokalnie, Contabo VPS produkcyjnie. Shell: PowerShell.

## Odchylenia od specu (świadome, po zbadaniu kodu)

Trzy rzeczy wyszły przy czytaniu kodu i zmieniają plan względem specu:

1. **Czwarta implementacja kosztów.** Spec wymienia trzy; jest też `kontekst ai/ai_repo/core/llm.py:87` (`_record` → `record_llm_call`). Konsekwencja pozytywna: to kolejny gotowy hook.
2. **RAG to jeden hook, nie trzy pliki.** `RAG/backend/services/chat_service.py:465` już iteruje po `call_records` zawierających `rewrite`/`embed`/`generate`/`judge` z providerem, modelem, tokenami i latencją. Drugi hook potrzebny tylko dla workerów ingestu, które wołają `core/embeddings.py` z pominięciem chat_service.
3. **Kolumna `tokens_estimated` dodana do schematu.** llm-proxy (`server.py:341`) i kontekst-ai (`llm.py:102`) liczą tokeny jako `len(tekst) // 4` — to zgadywanie, nie pomiar. Bez flagi dashboard zmiesza zmierzone tokeny ze zgadniętymi i nie da się ich rozdzielić. To ta sama klasa problemu, co `NULL` vs `0` przy brakującym cenniku.

## File Structure

**Nowy projekt `llmops/`:**

| Plik | Odpowiedzialność |
|---|---|
| `llmops/docker-compose.yml` | Postgres + kolektor, porty na Tailscale |
| `llmops/.env.example` | wzorzec konfiguracji |
| `llmops/db-init/01-schema.sql` | `llm_calls`, `model_pricing`, `v_llm_calls_costed` |
| `llmops/db-init/02-seed-pricing.sql` | cennik startowy |
| `llmops/collector/app.py` | FastAPI: `/v1/calls`, `/v1/calls/batch`, `/health` |
| `llmops/collector/db.py` | pula połączeń + `insert_calls()` |
| `llmops/collector/models.py` | Pydantic `CallIn` + walidacja i redakcja |
| `llmops/collector/Dockerfile`, `requirements.txt` | obraz kolektora |
| `llmops/client/llmops_client.py` | **kanoniczne** źródło klienta (kolejka + wątek roboczy) |
| `llmops/client/sync_clients.py` | kopiuje klienta do siedmiu projektów |
| `llmops/grafana/datasource-llmops.yml` | provisioned datasource |
| `llmops/grafana/dashboards/llm-observability.json` | dashboard |
| `llmops/scripts/retention.sh` | kasowanie wierszy > 90 dni |
| `llmops/tests/` | testy schematu, kolektora, klienta |
| `llmops/CLAUDE.md`, `llmops/README.md` | kontekst projektu + runbook |

**Modyfikowane pliki w istniejących projektach** (po jednej-dwie linie każdy, wymienione w zadaniach 4–6).

---

### Task 1: Stack `llmops` — baza, schemat, cennik

Deliverable: działający Postgres z tabelami i widokiem, w którym model bez cennika daje `NULL`, a nie `0`.

**Files:**
- Create: `llmops/docker-compose.yml`
- Create: `llmops/.env.example`
- Create: `llmops/db-init/01-schema.sql`
- Create: `llmops/db-init/02-seed-pricing.sql`
- Create: `llmops/tests/conftest.py`
- Test: `llmops/tests/test_schema.py`
- Create: `llmops/requirements-dev.txt`

**Interfaces:**
- Consumes: nic (pierwsze zadanie)
- Produces: baza `llmops` z tabelami `llm_calls`, `model_pricing` i widokiem `v_llm_calls_costed` zwracającym kolumny `effective_cost_usd NUMERIC` i `pricing_missing BOOLEAN`. Kolumny `llm_calls`: `id, ts, project, service, environment, host, provider, model, call_type, tokens_in, tokens_out, tokens_estimated, cost_usd, latency_ms, ok, error, trace_id`.

- [ ] **Step 1: Napisz schemat bazy**

Create `llmops/db-init/01-schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS llm_calls (
    id               BIGSERIAL PRIMARY KEY,
    ts               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    project          TEXT         NOT NULL,
    service          TEXT         NOT NULL,
    environment      TEXT         NOT NULL,
    host             TEXT         NOT NULL,
    provider         TEXT         NOT NULL,
    model            TEXT         NOT NULL,
    call_type        TEXT         NOT NULL,
    tokens_in        INTEGER      NOT NULL DEFAULT 0,
    tokens_out       INTEGER      NOT NULL DEFAULT 0,
    tokens_estimated BOOLEAN      NOT NULL DEFAULT FALSE,
    cost_usd         NUMERIC(12,6),
    latency_ms       INTEGER,
    ok               BOOLEAN      NOT NULL,
    error            TEXT,
    trace_id         TEXT
);

CREATE INDEX IF NOT EXISTS idx_llm_calls_ts         ON llm_calls (ts DESC);
CREATE INDEX IF NOT EXISTS idx_llm_calls_project_ts ON llm_calls (project, ts DESC);
CREATE INDEX IF NOT EXISTS idx_llm_calls_model_ts   ON llm_calls (model, ts DESC);

CREATE TABLE IF NOT EXISTS model_pricing (
    id               SERIAL PRIMARY KEY,
    provider         TEXT NOT NULL,
    model            TEXT NOT NULL,
    usd_per_mtok_in  NUMERIC(10,4) NOT NULL,
    usd_per_mtok_out NUMERIC(10,4) NOT NULL,
    valid_from       TIMESTAMPTZ   NOT NULL DEFAULT '1970-01-01T00:00:00Z',
    UNIQUE (provider, model, valid_from)
);

CREATE OR REPLACE VIEW v_llm_calls_costed AS
SELECT
    c.*,
    COALESCE(
        c.cost_usd,
        p.usd_per_mtok_in  * c.tokens_in  / 1e6
      + p.usd_per_mtok_out * c.tokens_out / 1e6
    )                                        AS effective_cost_usd,
    (c.cost_usd IS NULL AND p.id IS NULL)    AS pricing_missing
FROM llm_calls c
LEFT JOIN LATERAL (
    SELECT mp.id, mp.usd_per_mtok_in, mp.usd_per_mtok_out
    FROM model_pricing mp
    WHERE mp.provider = c.provider
      AND mp.model = c.model
      AND mp.valid_from <= c.ts
    ORDER BY mp.valid_from DESC
    LIMIT 1
) p ON TRUE;
```

- [ ] **Step 2: Napisz cennik startowy**

Create `llmops/db-init/02-seed-pricing.sql`. Ceny darmowe (`0,0`) są pewne — model darmowy kosztuje zero. **Ceny płatne poniżej są przepisane z kodu tego repo** (`argus/argus/llm/router.py:24`, `mcp-servers/llm-proxy/server.py:51`) i przed produkcyjnym zaufaniem liczbom trzeba je zweryfikować na stronach cenowych dostawców — to jest zadanie ręczne, wpisane do runbooka w Task 8.

```sql
INSERT INTO model_pricing (provider, model, usd_per_mtok_in, usd_per_mtok_out) VALUES
    ('ollama',     'ANY',                                        0.00,  0.00),
    ('groq',       'llama-3.3-70b-versatile',                    0.00,  0.00),
    ('gemini',     'gemini-flash-latest',                        0.00,  0.00),
    ('gemini',     'gemini-2.0-flash',                           0.00,  0.00),
    ('openrouter', 'meta-llama/llama-3.3-70b-instruct:free',     0.00,  0.00),
    ('openrouter', 'meta-llama/llama-4-maverick:free',           0.00,  0.00),
    ('openrouter', 'qwen/qwen3-235b-a22b:free',                  0.00,  0.00),
    ('openrouter', 'google/gemma-3-27b-it:free',                 0.00,  0.00),
    ('openrouter', 'openai/gpt-4o-mini',                         0.15,  0.60)
ON CONFLICT (provider, model, valid_from) DO NOTHING;
```

Uwaga: wiersz `('ollama', 'ANY', ...)` **nie działa** jako wildcard — widok dopasowuje model dokładnie. Zostaje jako czytelny znacznik, że Ollama jest darmowa; realne modele Ollamy dopisze runbook, gdy panel „pricing missing" je pokaże. To celowe: wolimy zobaczyć lukę niż po cichu wyzerować koszt.

- [ ] **Step 3: Napisz compose**

Create `llmops/docker-compose.yml`:

```yaml
services:
  llmops-postgres:
    image: postgres:16-alpine
    container_name: llmops-postgres
    restart: unless-stopped
    ports:
      - "${TAILSCALE_IP:-127.0.0.1}:5436:5432"
    environment:
      POSTGRES_USER: ${LLMOPS_DB_USER:-llmops}
      POSTGRES_PASSWORD: ${LLMOPS_DB_PASSWORD:-llmopspass}
      POSTGRES_DB: ${LLMOPS_DB_NAME:-llmops}
    volumes:
      - llmops-postgres-data:/var/lib/postgresql/data
      - ./db-init:/docker-entrypoint-initdb.d
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${LLMOPS_DB_USER:-llmops} -d ${LLMOPS_DB_NAME:-llmops}"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  llmops-postgres-data:
```

Create `llmops/.env.example`:

```
TAILSCALE_IP=127.0.0.1
LLMOPS_DB_USER=llmops
LLMOPS_DB_PASSWORD=changeme
LLMOPS_DB_NAME=llmops
LLMOPS_TOKEN=changeme-shared-bearer-token
```

Create `llmops/requirements-dev.txt`:

```
pytest==8.3.*
psycopg2-binary==2.9.*
httpx==0.27.*
```

- [ ] **Step 4: Napisz fixture testowy**

Create `llmops/tests/conftest.py`:

```python
import os
import psycopg2
import pytest

DSN = os.getenv(
    "LLMOPS_TEST_DSN",
    "postgresql://llmops:llmopspass@127.0.0.1:5436/llmops",
)


@pytest.fixture
def db():
    """Realna baza — nie mock. Widok liczy koszt w Postgresie, więc testujemy Postgres."""
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("TRUNCATE llm_calls RESTART IDENTITY")
        cur.execute("DELETE FROM model_pricing")
    yield conn
    conn.close()


def insert_call(conn, **kw):
    cols = {
        "project": "test", "service": "test", "environment": "test",
        "host": "test", "provider": "openrouter", "model": "m",
        "call_type": "generate", "tokens_in": 0, "tokens_out": 0, "ok": True,
    }
    cols.update(kw)
    names = ", ".join(cols)
    marks = ", ".join(["%s"] * len(cols))
    with conn.cursor() as cur:
        cur.execute(f"INSERT INTO llm_calls ({names}) VALUES ({marks}) RETURNING id",
                    list(cols.values()))
        return cur.fetchone()[0]
```

- [ ] **Step 5: Napisz failujące testy widoku**

Create `llmops/tests/test_schema.py`:

```python
from conftest import insert_call


def test_cost_computed_from_pricing(db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO model_pricing (provider, model, usd_per_mtok_in, usd_per_mtok_out)"
            " VALUES ('openrouter', 'openai/gpt-4o-mini', 0.15, 0.60)"
        )
    insert_call(db, model="openai/gpt-4o-mini", tokens_in=1_000_000, tokens_out=1_000_000)
    with db.cursor() as cur:
        cur.execute("SELECT effective_cost_usd, pricing_missing FROM v_llm_calls_costed")
        cost, missing = cur.fetchone()
    assert float(cost) == 0.75
    assert missing is False


def test_missing_pricing_gives_null_not_zero(db):
    insert_call(db, model="nieznany/model", tokens_in=1_000_000, tokens_out=1_000_000)
    with db.cursor() as cur:
        cur.execute("SELECT effective_cost_usd, pricing_missing FROM v_llm_calls_costed")
        cost, missing = cur.fetchone()
    assert cost is None, "brak cennika musi dawać NULL, nie 0 — inaczej koszt cicho znika"
    assert missing is True


def test_explicit_cost_wins_over_pricing(db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO model_pricing (provider, model, usd_per_mtok_in, usd_per_mtok_out)"
            " VALUES ('openrouter', 'm', 100.0, 100.0)"
        )
    insert_call(db, cost_usd=0.5, tokens_in=1_000_000, tokens_out=1_000_000)
    with db.cursor() as cur:
        cur.execute("SELECT effective_cost_usd FROM v_llm_calls_costed")
        assert float(cur.fetchone()[0]) == 0.5


def test_pricing_is_versioned_by_valid_from(db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO model_pricing (provider, model, usd_per_mtok_in, usd_per_mtok_out, valid_from)"
            " VALUES ('openrouter', 'm', 1.0, 0.0, '2020-01-01Z'),"
            "        ('openrouter', 'm', 2.0, 0.0, '2030-01-01Z')"
        )
    insert_call(db, tokens_in=1_000_000, ts="2025-01-01Z")
    with db.cursor() as cur:
        cur.execute("SELECT effective_cost_usd FROM v_llm_calls_costed")
        assert float(cur.fetchone()[0]) == 1.0, "musi obowiązywać cennik z momentu wywołania"


def test_free_model_is_zero_not_null(db):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO model_pricing (provider, model, usd_per_mtok_in, usd_per_mtok_out)"
            " VALUES ('openrouter', 'darmowy:free', 0.0, 0.0)"
        )
    insert_call(db, model="darmowy:free", tokens_in=1_000_000)
    with db.cursor() as cur:
        cur.execute("SELECT effective_cost_usd, pricing_missing FROM v_llm_calls_costed")
        cost, missing = cur.fetchone()
    assert float(cost) == 0.0
    assert missing is False
```

- [ ] **Step 6: Uruchom testy — muszą failować**

```powershell
cd llmops
pytest tests/test_schema.py -v
```

Expected: FAIL — `psycopg2.OperationalError` (baza nie wstała).

- [ ] **Step 7: Podnieś stack i uruchom testy ponownie**

```powershell
cd llmops
Copy-Item .env.example .env
docker compose up -d
docker compose ps
pytest tests/test_schema.py -v
```

Expected: 5 passed. Jeśli `insert_call` z parametrem `ts` failuje — kolumna `ts` ma default, ale jawne podanie musi działać; to poprawny test, napraw `insert_call`, nie test.

- [ ] **Step 8: Commit**

```bash
git add llmops/
git commit -m "feat(llmops): baza, schemat i wersjonowany cennik modeli"
```

---

### Task 2: Kolektor HTTP

Deliverable: usługa przyjmująca metadane wywołań, odrzucająca treści, pisząca do bazy z Task 1.

**Files:**
- Create: `llmops/collector/models.py`
- Create: `llmops/collector/db.py`
- Create: `llmops/collector/app.py`
- Create: `llmops/collector/requirements.txt`
- Create: `llmops/collector/Dockerfile`
- Modify: `llmops/docker-compose.yml` (dodanie usługi `llmops-collector`)
- Test: `llmops/tests/test_collector.py`

**Interfaces:**
- Consumes: baza i schemat z Task 1.
- Produces: HTTP API — `POST /v1/calls` (jeden obiekt) i `POST /v1/calls/batch` (lista ≤ 100) zwracające `202`, `GET /health` zwracające `{"status": "ok"}`. Nagłówek `Authorization: Bearer <LLMOPS_TOKEN>` wymagany na `/v1/*`. Pola ładunku zgodne z `CallIn` poniżej.

- [ ] **Step 1: Napisz model i walidację**

Create `llmops/collector/models.py`:

```python
import re
from pydantic import BaseModel, Field, field_validator, model_validator

# Pola, których tu nie trzymamy — treści idą do Langfuse (Etap 3), nie tutaj.
FORBIDDEN_FIELDS = {"prompt", "response", "input", "output", "messages", "context"}

_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|AIza[A-Za-z0-9_\-]{10,}|Bearer\s+\S+)")


class CallIn(BaseModel):
    model_config = {"extra": "forbid"}

    project: str = Field(max_length=64)
    service: str = Field(max_length=64)
    environment: str = Field(max_length=32)
    host: str = Field(max_length=64)
    provider: str = Field(max_length=32)
    model: str = Field(max_length=200)
    call_type: str = Field(max_length=32)
    tokens_in: int = Field(default=0, ge=0)
    tokens_out: int = Field(default=0, ge=0)
    tokens_estimated: bool = False
    cost_usd: float | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    ok: bool
    error: str | None = None
    trace_id: str | None = Field(default=None, max_length=128)

    @field_validator("error")
    @classmethod
    def redact_and_truncate(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _SECRET_RE.sub("[REDACTED]", v)[:300]

    @model_validator(mode="before")
    @classmethod
    def reject_content(cls, data):
        if isinstance(data, dict):
            found = FORBIDDEN_FIELDS & set(data)
            if found:
                raise ValueError(f"pola z trescia sa zabronione: {sorted(found)}")
        return data
```

`extra: forbid` sam odrzuciłby nieznane pola, ale osobny walidator daje czytelny komunikat, że to świadoma granica projektu, a nie literówka w nazwie pola.

- [ ] **Step 2: Napisz warstwę bazy**

Create `llmops/collector/db.py`:

```python
import os
from psycopg2.pool import ThreadedConnectionPool

_pool: ThreadedConnectionPool | None = None

_COLUMNS = (
    "project", "service", "environment", "host", "provider", "model",
    "call_type", "tokens_in", "tokens_out", "tokens_estimated",
    "cost_usd", "latency_ms", "ok", "error", "trace_id",
)

_SQL = (
    f"INSERT INTO llm_calls ({', '.join(_COLUMNS)}) "
    f"VALUES ({', '.join(['%s'] * len(_COLUMNS))})"
)


def get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(1, 10, dsn=os.environ["LLMOPS_DSN"])
    return _pool


def insert_calls(calls: list[dict]) -> int:
    rows = [tuple(c.get(col) for col in _COLUMNS) for c in calls]
    pool = get_pool()
    conn = pool.getconn()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.executemany(_SQL, rows)
        return len(rows)
    finally:
        pool.putconn(conn)


def ping() -> None:
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
    finally:
        pool.putconn(conn)
```

- [ ] **Step 3: Napisz aplikację**

Create `llmops/collector/app.py`:

```python
import os
from fastapi import Depends, FastAPI, Header, HTTPException, Response

from db import insert_calls, ping
from models import CallIn

app = FastAPI(title="llmops-collector")

MAX_BATCH = 100


def require_token(authorization: str = Header(default="")) -> None:
    expected = os.environ.get("LLMOPS_TOKEN", "")
    if not expected or authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="bad token")


@app.get("/health")
def health():
    ping()
    return {"status": "ok"}


@app.post("/v1/calls", status_code=202, dependencies=[Depends(require_token)])
def post_call(call: CallIn):
    insert_calls([call.model_dump()])
    return Response(status_code=202)


@app.post("/v1/calls/batch", status_code=202, dependencies=[Depends(require_token)])
def post_batch(calls: list[CallIn]):
    if len(calls) > MAX_BATCH:
        raise HTTPException(status_code=413, detail=f"max {MAX_BATCH} per batch")
    insert_calls([c.model_dump() for c in calls])
    return Response(status_code=202)
```

Create `llmops/collector/requirements.txt`:

```
fastapi==0.115.*
uvicorn[standard]==0.32.*
pydantic==2.*
psycopg2-binary==2.9.*
```

Create `llmops/collector/Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
```

`--host 0.0.0.0` wewnątrz kontenera jest w porządku — ekspozycję na świat ogranicza binding portu w compose, nie uvicorn.

- [ ] **Step 4: Dopisz usługę do compose**

Modify `llmops/docker-compose.yml` — dodaj przed sekcją `volumes:`:

```yaml
  llmops-collector:
    build:
      context: ./collector
    container_name: llmops-collector
    restart: unless-stopped
    ports:
      - "${TAILSCALE_IP:-127.0.0.1}:8090:8080"
    environment:
      LLMOPS_DSN: postgresql://${LLMOPS_DB_USER:-llmops}:${LLMOPS_DB_PASSWORD:-llmopspass}@llmops-postgres:5432/${LLMOPS_DB_NAME:-llmops}
      LLMOPS_TOKEN: ${LLMOPS_TOKEN}
    depends_on:
      llmops-postgres:
        condition: service_healthy
```

- [ ] **Step 5: Napisz failujące testy kolektora**

Create `llmops/tests/test_collector.py`:

```python
import os
import httpx
import pytest

BASE = os.getenv("LLMOPS_TEST_URL", "http://127.0.0.1:8090")
TOKEN = os.getenv("LLMOPS_TOKEN", "changeme-shared-bearer-token")
AUTH = {"Authorization": f"Bearer {TOKEN}"}

VALID = {
    "project": "rag", "service": "chat-api", "environment": "test",
    "host": "local", "provider": "openrouter", "model": "openai/gpt-4o-mini",
    "call_type": "generate", "tokens_in": 10, "tokens_out": 20,
    "latency_ms": 150, "ok": True,
}


def test_health_ok():
    r = httpx.get(f"{BASE}/health", timeout=5)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_valid_call_is_stored(db):
    r = httpx.post(f"{BASE}/v1/calls", json=VALID, headers=AUTH, timeout=5)
    assert r.status_code == 202
    with db.cursor() as cur:
        cur.execute("SELECT project, model, tokens_in, ok FROM llm_calls")
        assert cur.fetchall() == [("rag", "openai/gpt-4o-mini", 10, True)]


def test_missing_token_rejected():
    r = httpx.post(f"{BASE}/v1/calls", json=VALID, timeout=5)
    assert r.status_code == 401


def test_payload_with_prompt_rejected(db):
    bad = dict(VALID, prompt="tajna tresc uzytkownika")
    r = httpx.post(f"{BASE}/v1/calls", json=bad, headers=AUTH, timeout=5)
    assert r.status_code == 422
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM llm_calls")
        assert cur.fetchone()[0] == 0


def test_api_key_in_error_is_redacted(db):
    payload = dict(VALID, ok=False, error="401 from provider, key sk-abcdef1234567890 rejected")
    r = httpx.post(f"{BASE}/v1/calls", json=payload, headers=AUTH, timeout=5)
    assert r.status_code == 202
    with db.cursor() as cur:
        cur.execute("SELECT error FROM llm_calls")
        stored = cur.fetchone()[0]
    assert "sk-abcdef1234567890" not in stored
    assert "[REDACTED]" in stored


def test_long_error_is_truncated(db):
    payload = dict(VALID, ok=False, error="x" * 5000)
    httpx.post(f"{BASE}/v1/calls", json=payload, headers=AUTH, timeout=5)
    with db.cursor() as cur:
        cur.execute("SELECT length(error) FROM llm_calls")
        assert cur.fetchone()[0] == 300


def test_batch_is_stored(db):
    r = httpx.post(f"{BASE}/v1/calls/batch", json=[VALID, VALID, VALID],
                   headers=AUTH, timeout=5)
    assert r.status_code == 202
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM llm_calls")
        assert cur.fetchone()[0] == 3


def test_oversized_batch_rejected():
    r = httpx.post(f"{BASE}/v1/calls/batch", json=[VALID] * 101, headers=AUTH, timeout=5)
    assert r.status_code == 413
```

- [ ] **Step 6: Uruchom testy — muszą failować**

```powershell
cd llmops
pytest tests/test_collector.py -v
```

Expected: FAIL — `httpx.ConnectError` (kolektor nie działa).

- [ ] **Step 7: Zbuduj i uruchom, potem testy ponownie**

```powershell
cd llmops
docker compose up -d --build
docker compose logs llmops-collector --tail 30
pytest tests/ -v
```

Expected: 13 passed (5 ze schematu + 8 z kolektora).

- [ ] **Step 8: Commit**

```bash
git add llmops/
git commit -m "feat(llmops): kolektor HTTP z redakcja bledow i blokada tresci"
```

---

### Task 3: Klient `llmops_client`

Deliverable: moduł, który nie blokuje, nie rzuca wyjątków i jest no-op bez konfiguracji.

**Files:**
- Create: `llmops/client/llmops_client.py`
- Create: `llmops/client/sync_clients.py`
- Test: `llmops/tests/test_client.py`

**Interfaces:**
- Consumes: kolektor z Task 2.
- Produces: `llmops_client.record(provider: str, model: str, call_type: str, tokens_in: int = 0, tokens_out: int = 0, latency_ms: int | None = None, ok: bool = True, error: str | None = None, cost_usd: float | None = None, tokens_estimated: bool = False, trace_id: str | None = None) -> None` — zawsze zwraca `None`, nigdy nie podnosi wyjątku. Plus `llmops_client.flush(timeout: float = 5.0) -> None` do użycia w testach i przy zamykaniu procesu.

- [ ] **Step 1: Napisz klienta**

Create `llmops/client/llmops_client.py`:

```python
"""Klient telemetrii LLMOps — kolejka w pamieci + watek roboczy.

KANONICZNE ZRODLO: llmops/client/llmops_client.py
Kopie w innych projektach sa generowane przez llmops/client/sync_clients.py.
Nie edytuj kopii — edytuj oryginal i uruchom sync.

Zasada: telemetria nigdy nie wywraca ani nie spowalnia wywolania LLM.
Kolejka pelna -> gubimy metryke. Kolektor lezy -> gubimy metryke. Nigdy wyjatek.
"""
import atexit
import json
import logging
import os
import queue
import threading
import urllib.request

logger = logging.getLogger("llmops")

_URL = os.getenv("LLMOPS_URL", "").rstrip("/")
_TOKEN = os.getenv("LLMOPS_TOKEN", "")
_DIMS = {
    "project": os.getenv("LLMOPS_PROJECT", "unknown"),
    "service": os.getenv("LLMOPS_SERVICE", "unknown"),
    "environment": os.getenv("LLMOPS_ENV", "unknown"),
    "host": os.getenv("LLMOPS_HOST", "unknown"),
}

_QUEUE_MAX = int(os.getenv("LLMOPS_QUEUE_MAX", "1000"))
_BATCH_MAX = 100
_TIMEOUT = float(os.getenv("LLMOPS_TIMEOUT", "2.0"))

_q: queue.Queue = queue.Queue(maxsize=_QUEUE_MAX)
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()
_dropped = 0


def _post(payload: list[dict]) -> None:
    req = urllib.request.Request(
        f"{_URL}/v1/calls/batch",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {_TOKEN}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT):
        pass


def _drain() -> None:
    while True:
        item = _q.get()
        batch = [item]
        while len(batch) < _BATCH_MAX:
            try:
                batch.append(_q.get_nowait())
            except queue.Empty:
                break
        try:
            _post(batch)
        except Exception as exc:
            logger.warning("llmops: %d metryk utraconych: %s", len(batch), exc)
        finally:
            for _ in batch:
                _q.task_done()


def _ensure_worker() -> None:
    global _worker
    if _worker is not None and _worker.is_alive():
        return
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_drain, name="llmops", daemon=True)
            _worker.start()


def record(provider: str, model: str, call_type: str, tokens_in: int = 0,
           tokens_out: int = 0, latency_ms: int | None = None, ok: bool = True,
           error: str | None = None, cost_usd: float | None = None,
           tokens_estimated: bool = False, trace_id: str | None = None) -> None:
    """Zapisz metadane jednego wywolania LLM. Nigdy nie podnosi wyjatku."""
    global _dropped
    if not _URL:
        return
    try:
        _ensure_worker()
        _q.put_nowait({
            **_DIMS,
            "provider": provider, "model": model, "call_type": call_type,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "tokens_estimated": tokens_estimated, "cost_usd": cost_usd,
            "latency_ms": latency_ms, "ok": ok,
            "error": error, "trace_id": trace_id,
        })
    except queue.Full:
        _dropped += 1
        if _dropped % 100 == 1:
            logger.warning("llmops: kolejka pelna, %d metryk odrzuconych", _dropped)
    except Exception as exc:
        logger.warning("llmops: record nieudany: %s", exc)


def flush(timeout: float = 5.0) -> None:
    """Poczekaj na oproznienie kolejki. Do testow i zamykania procesu."""
    if not _URL:
        return
    done = threading.Event()
    threading.Thread(target=lambda: (_q.join(), done.set()), daemon=True).start()
    done.wait(timeout)


atexit.register(flush)
```

Klient używa `urllib` ze standardowej biblioteki, nie `httpx`/`requests` — siedem projektów ma siedem różnych zestawów zależności, a telemetria nie ma prawa niczego do nich dokładać.

- [ ] **Step 2: Napisz failujące testy klienta**

Create `llmops/tests/test_client.py`:

```python
import importlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

sys.path.insert(0, "client")

RECEIVED: list = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        RECEIVED.append({"path": self.path,
                         "auth": self.headers.get("Authorization"),
                         "body": json.loads(body)})
        self.send_response(202)
        self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture
def collector():
    """Prawdziwy serwer HTTP, nie mock — testujemy sciezke sieciowa klienta."""
    RECEIVED.clear()
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", RECEIVED
    srv.shutdown()


def _fresh_client(monkeypatch, url: str):
    monkeypatch.setenv("LLMOPS_URL", url)
    monkeypatch.setenv("LLMOPS_TOKEN", "t0k")
    monkeypatch.setenv("LLMOPS_PROJECT", "argus")
    monkeypatch.setenv("LLMOPS_SERVICE", "collector")
    monkeypatch.setenv("LLMOPS_ENV", "test")
    monkeypatch.setenv("LLMOPS_HOST", "local")
    import llmops_client
    return importlib.reload(llmops_client)


def test_record_reaches_collector(monkeypatch, collector):
    url, received = collector
    c = _fresh_client(monkeypatch, url)
    c.record(provider="gemini", model="gemini-flash-latest", call_type="generate",
             tokens_in=5, tokens_out=7, latency_ms=120, ok=True)
    c.flush()
    assert len(received) == 1
    assert received[0]["path"] == "/v1/calls/batch"
    assert received[0]["auth"] == "Bearer t0k"
    row = received[0]["body"][0]
    assert row["project"] == "argus"
    assert row["service"] == "collector"
    assert row["provider"] == "gemini"
    assert row["tokens_in"] == 5


def test_no_url_is_noop(monkeypatch):
    monkeypatch.setenv("LLMOPS_URL", "")
    import llmops_client
    c = importlib.reload(llmops_client)
    c.record(provider="x", model="y", call_type="generate")
    c.flush()


def test_collector_down_does_not_raise(monkeypatch):
    c = _fresh_client(monkeypatch, "http://127.0.0.1:1")
    c.record(provider="x", model="y", call_type="generate")
    c.flush(timeout=3)


def test_full_queue_drops_without_raising(monkeypatch, collector):
    url, _ = collector
    monkeypatch.setenv("LLMOPS_QUEUE_MAX", "2")
    c = _fresh_client(monkeypatch, url)
    for _ in range(500):
        c.record(provider="x", model="y", call_type="generate")
    c.flush(timeout=3)


def test_batches_multiple_records(monkeypatch, collector):
    url, received = collector
    c = _fresh_client(monkeypatch, url)
    for i in range(20):
        c.record(provider="x", model=f"m{i}", call_type="generate")
    c.flush(timeout=5)
    total = sum(len(r["body"]) for r in received)
    assert total == 20
```

- [ ] **Step 3: Uruchom testy — muszą failować**

```powershell
cd llmops
pytest tests/test_client.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'llmops_client'` przed napisaniem pliku, albo `AssertionError` jeśli plik istnieje niekompletny.

- [ ] **Step 4: Uruchom testy po napisaniu klienta**

```powershell
cd llmops
pytest tests/test_client.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Napisz skrypt synchronizujący kopie**

Create `llmops/client/sync_clients.py`:

```python
"""Kopiuje kanonicznego klienta do wszystkich projektow.

Uruchom z katalogu llmops/:  python client/sync_clients.py [--check]
--check zwraca kod 1, gdy ktoras kopia sie rozjechala (do CI).
"""
import hashlib
import shutil
import sys
from pathlib import Path

SRC = Path(__file__).parent / "llmops_client.py"

TARGETS = [
    Path("../RAG/backend/core/llmops_client.py"),
    Path("../argus/argus/llmops_client.py"),
    Path("../mcp-servers/llm-proxy/llmops_client.py"),
    Path("../Selfmadeagent/orchestrator/agent/llmops_client.py"),
    Path("../kontekst ai/ai_repo/core/llmops_client.py"),
    Path("../trading-app/core/llmops_client.py"),
]


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    check = "--check" in sys.argv
    src_hash = digest(SRC)
    drift = []
    for t in TARGETS:
        t = (Path(__file__).parent / t).resolve()
        if check:
            if not t.exists() or digest(t) != src_hash:
                drift.append(str(t))
        else:
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SRC, t)
            print(f"synced -> {t}")
    if check and drift:
        print("ROZJECHANE KOPIE:\n  " + "\n  ".join(drift))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Hermes nie ma wpisu — chodzi przez `llm-proxy`, więc jest pokryty pośrednio.

- [ ] **Step 6: Rozprowadź klienta i sprawdź spójność**

```powershell
cd llmops
python client/sync_clients.py
python client/sync_clients.py --check
```

Expected: sześć linii `synced ->`, potem `--check` kończy się kodem 0.

- [ ] **Step 7: Commit**

```bash
git add llmops/ RAG/backend/core/llmops_client.py argus/argus/llmops_client.py mcp-servers/llm-proxy/llmops_client.py Selfmadeagent/orchestrator/agent/llmops_client.py "kontekst ai/ai_repo/core/llmops_client.py" trading-app/core/llmops_client.py
git commit -m "feat(llmops): klient telemetrii + synchronizacja kopii do projektow"
```

---

### Task 4: Wpięcie Argusa i llm-proxy (gotowe hooki)

Deliverable: dwa projekty o największym wolumenie raportują do centralnej bazy; Hermes wchodzi przy okazji przez llm-proxy.

**Files:**
- Modify: `argus/argus/llm/router.py:120-131` (funkcja `_record`)
- Modify: `mcp-servers/llm-proxy/server.py:84-94` (koniec `_record_cost`)
- Modify: `argus/docker-compose.yml` (env dla `app`, `liq-listener`, `argus-guardian`)
- Test: `argus/tests/test_llm_router.py` (dopisanie jednego testu)
- Test: `mcp-servers/llm-proxy/tests/test_server.py` (dopisanie jednego testu)

**Interfaces:**
- Consumes: `llmops_client.record(...)` z Task 3.
- Produces: wiersze `llm_calls` z `project='argus'` i `project='llm-proxy'`.

- [ ] **Step 1: Napisz failujący test dla Argusa**

Append to `argus/tests/test_llm_router.py`:

```python
def test_record_emits_to_llmops_even_when_db_write_fails(monkeypatch):
    """Telemetria centralna nie moze zalezec od tego, czy lokalny zapis do DB przeszedl."""
    import argus.llmops_client as llmops
    sent = []
    monkeypatch.setattr(llmops, "record", lambda **kw: sent.append(kw))

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr("argus.db.SessionLocal", boom)
    router._record("gemini", "gemini-flash-latest",
                   {"tokens_in": 11, "tokens_out": 22}, 150, True, None)

    assert len(sent) == 1
    assert sent[0]["provider"] == "gemini"
    assert sent[0]["tokens_in"] == 11
    assert sent[0]["ok"] is True
```

- [ ] **Step 2: Uruchom test — musi failować**

```powershell
cd argus
pytest tests/test_llm_router.py::test_record_emits_to_llmops_even_when_db_write_fails -v
```

Expected: FAIL — `assert 0 == 1` (nic nie wysłano).

- [ ] **Step 3: Wepnij Argusa**

Modify `argus/argus/llm/router.py` — funkcja `_record` kończy się dziś na `logger.warning("llm_call record failed: %s", e)`. Dopisz **nowy, osobny** blok na końcu funkcji, poza istniejącym `try`:

```python
def _record(provider: str, model: str, usage: dict, latency_ms: int, ok: bool, error):
    try:
        from argus.db import SessionLocal
        from argus.models import LlmCall
        with SessionLocal() as s:
            s.add(LlmCall(ts=datetime.now(timezone.utc), provider=provider, model=model,
                          tokens_in=usage.get("tokens_in", 0), tokens_out=usage.get("tokens_out", 0),
                          cost_usd=_cost(model, usage), latency_ms=latency_ms, ok=ok,
                          error=(error[:300] if error else None)))
            s.commit()
    except Exception as e:
        logger.warning("llm_call record failed: %s", e)

    try:
        from argus.llmops_client import record as _llmops_record
        _llmops_record(provider=provider, model=model, call_type="generate",
                       tokens_in=usage.get("tokens_in", 0),
                       tokens_out=usage.get("tokens_out", 0),
                       latency_ms=latency_ms, ok=ok,
                       error=(str(error) if error else None))
    except Exception:
        pass
```

Osobny `try` jest istotą tego zadania: gdyby emisja siedziała w tym samym bloku co zapis do bazy, padnięcie bazy Argusa zabierałoby ze sobą telemetrię centralną. Nie przekazujemy `cost_usd` — koszt liczy widok z cennika, a lokalny `_cost` zna jeden model.

- [ ] **Step 4: Uruchom testy Argusa**

```powershell
cd argus
pytest tests/test_llm_router.py -v
```

Expected: wszystkie przechodzą, łącznie z nowym. Istniejące testy podmieniają całe `_record`, więc pozostają zielone.

- [ ] **Step 5: Napisz failujący test dla llm-proxy**

Append to `mcp-servers/llm-proxy/tests/test_server.py`:

```python
def test_record_cost_emits_to_llmops(monkeypatch):
    import llmops_client
    import server
    sent = []
    monkeypatch.setattr(llmops_client, "record", lambda **kw: sent.append(kw))
    monkeypatch.setattr(server, "_insert_pg", lambda **kw: None)

    server._record_cost("ask_openrouter", "google/gemma-3-27b-it:free",
                        100, 200, 0.0, skill="research", latency_ms=900, error=None)

    assert len(sent) == 1
    assert sent[0]["provider"] == "openrouter"
    assert sent[0]["model"] == "google/gemma-3-27b-it:free"
    assert sent[0]["tokens_estimated"] is True
    assert sent[0]["ok"] is True
```

- [ ] **Step 6: Uruchom test — musi failować**

```powershell
cd mcp-servers/llm-proxy
pytest tests/test_server.py::test_record_cost_emits_to_llmops -v
```

Expected: FAIL — `assert 0 == 1`.

- [ ] **Step 7: Wepnij llm-proxy**

Modify `mcp-servers/llm-proxy/server.py` — na końcu `_record_cost`, po wywołaniu `_insert_pg(...)`, dopisz:

```python
    try:
        from llmops_client import record as _llmops_record
        _llmops_record(
            provider=tool.replace("ask_", ""),
            model=model,
            call_type="generate",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_estimated=True,
            latency_ms=latency_ms,
            ok=error is None,
            error=error,
        )
    except Exception:
        pass
```

`tokens_estimated=True` jest tu prawdą, nie ostrożnością: `server.py:341` liczy tokeny jako `len(prompt) // 4`. Bez tej flagi zgadywanki wpadłyby do sumy kosztów nieodróżnialne od pomiarów.

- [ ] **Step 8: Uruchom testy llm-proxy**

```powershell
cd mcp-servers/llm-proxy
pytest tests/ -v
```

Expected: wszystkie przechodzą.

- [ ] **Step 9: Dodaj env do compose Argusa**

Modify `argus/docker-compose.yml` — do usług `app`, `liq-listener` i `argus-guardian` dopisz w sekcji `environment`:

```yaml
      LLMOPS_URL: ${LLMOPS_URL:-}
      LLMOPS_TOKEN: ${LLMOPS_TOKEN:-}
      LLMOPS_PROJECT: argus
      LLMOPS_SERVICE: app          # liq-listener / guardian w pozostalych dwoch
      LLMOPS_ENV: production
      LLMOPS_HOST: contabo-vps
```

Pusty `LLMOPS_URL` czyni klienta no-opem, więc brak konfiguracji nie psuje niczego lokalnie.

- [ ] **Step 10: Commit**

```bash
git add argus/ mcp-servers/llm-proxy/
git commit -m "feat(llmops): telemetria z argusa i llm-proxy (hermes posrednio)"
```

---

### Task 5: Wpięcie RAG-a

Deliverable: cztery typy wywołań ze ścieżki czatu (`rewrite`, `embed`, `generate`, `judge`) plus embeddingi z workerów ingestu.

**Files:**
- Modify: `RAG/backend/services/chat_service.py:462-477` (blok zapisu `LlmCall`)
- Modify: `RAG/backend/core/embeddings.py` (ścieżka używana przez workery)
- Modify: `RAG/docker-compose.vps.yml` (env dla `rag-backend` i `rag-worker`)
- Test: `RAG/backend/tests/test_llmops_emission.py`

**Interfaces:**
- Consumes: `llmops_client.record(...)` z Task 3, dostępny jako `core.llmops_client`.
- Produces: wiersze `llm_calls` z `project='rag'`, `service` w `{chat-api, worker}`.

- [ ] **Step 1: Napisz failujący test**

Create `RAG/backend/tests/test_llmops_emission.py`:

```python
import core.llmops_client as llmops
from services.chat_service import emit_llmops_calls


def test_emits_one_row_per_call_record(monkeypatch):
    sent = []
    monkeypatch.setattr(llmops, "record", lambda **kw: sent.append(kw))
    records = [
        {"call_type": "rewrite", "provider": "openrouter", "model": "m1",
         "tokens_in": 10, "tokens_out": 5, "latency_ms": 100},
        {"call_type": "generate", "provider": "ollama", "model": "m2",
         "tokens_in": 900, "tokens_out": 300, "latency_ms": 2000},
    ]
    emit_llmops_calls(records)
    assert [s["call_type"] for s in sent] == ["rewrite", "generate"]
    assert sent[1]["model"] == "m2"
    assert sent[1]["ok"] is True


def test_emission_survives_broken_record(monkeypatch):
    """Jeden zepsuty wpis nie moze zabrac pozostalych ani wywalic odpowiedzi."""
    sent = []
    monkeypatch.setattr(llmops, "record", lambda **kw: sent.append(kw))
    records = [
        {"nonsens": True},
        {"call_type": "judge", "provider": "openrouter", "model": "m3",
         "tokens_in": 1, "tokens_out": 1, "latency_ms": 10},
    ]
    emit_llmops_calls(records)
    assert len(sent) == 1
    assert sent[0]["call_type"] == "judge"
```

- [ ] **Step 2: Uruchom test — musi failować**

```powershell
cd RAG/backend
pytest tests/test_llmops_emission.py -v
```

Expected: FAIL — `ImportError: cannot import name 'emit_llmops_calls'`.

- [ ] **Step 3: Dodaj funkcję emisji**

Modify `RAG/backend/services/chat_service.py` — dopisz funkcję modułową obok istniejącego `_call_cost` (okolice linii 32):

```python
def emit_llmops_calls(call_records: list[dict]) -> None:
    """Wyslij metadane wywolan do centralnej telemetrii. Nigdy nie podnosi wyjatku."""
    from core import llmops_client
    for rec in call_records:
        try:
            llmops_client.record(
                provider=rec["provider"],
                model=rec["model"],
                call_type=rec["call_type"],
                tokens_in=rec["tokens_in"],
                tokens_out=rec["tokens_out"],
                latency_ms=rec.get("latency_ms"),
                ok=True,
            )
        except Exception:
            continue
```

- [ ] **Step 4: Wywołaj emisję poza blokiem zapisu do bazy**

Modify `RAG/backend/services/chat_service.py` — w bloku `finally` funkcji `query_stream`, zaraz **za** `except Exception as exc: logger.error("Failed to save assistant message: %s", exc)` (linia ~477), na tym samym poziomie wcięcia co `try`:

```python
                emit_llmops_calls(call_records)
```

Poza `try` zapisu do bazy, bo awaria bazy RAG-a nie może zabierać telemetrii centralnej — dokładnie ta sama zasada, co w Argusie w Task 4.

- [ ] **Step 5: Uruchom test**

```powershell
cd RAG/backend
pytest tests/test_llmops_emission.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Wepnij embeddingi workerów**

Modify `RAG/backend/core/embeddings.py` — najpierw przeczytaj plik i znajdź funkcję zwracającą embeddingi wraz z liczbą tokenów (ta sama, z której `chat_service.py:261` bierze `u["provider"]`, `u["model"]`, `u["tokens"]`, `u["latency_ms"]`). Na jej końcu, po udanym wywołaniu, dopisz:

```python
        try:
            from core import llmops_client
            llmops_client.record(
                provider=provider, model=model, call_type="embed",
                tokens_in=tokens, tokens_out=0, latency_ms=latency_ms, ok=True,
            )
        except Exception:
            pass
```

Nazwy zmiennych dopasuj do tych, które faktycznie są w tej funkcji — nie wprowadzaj nowych. Ścieżka czatu jest już pokryta Krokiem 4, więc **jeśli ta sama funkcja obsługuje oba przypadki, pojawi się podwójny zapis**. Zweryfikuj to w Kroku 7 i jeśli tak jest, zostaw wyłącznie hook w `embeddings.py`, a `embed` usuń z pętli `emit_llmops_calls` filtrem `if rec["call_type"] == "embed": continue`.

- [ ] **Step 7: Zweryfikuj brak podwójnych zapisów na żywym stacku**

```powershell
cd RAG
docker compose -f docker-compose.vps.yml up -d --build rag-backend
# zadaj jedno pytanie w UI czatu, potem:
docker exec llmops-postgres psql -U llmops -d llmops -c "SELECT call_type, count(*) FROM llm_calls WHERE project='rag' GROUP BY call_type"
```

Expected: po jednym pytaniu `generate` = 1. Jeśli `embed` > liczba faktycznych embeddingów, zastosuj filtr z Kroku 6.

- [ ] **Step 8: Dodaj env do compose RAG-a**

Modify `RAG/docker-compose.vps.yml` — do `rag-backend` i `rag-worker`, obok istniejącego `LANGFUSE_HOST`:

```yaml
      LLMOPS_URL: ${LLMOPS_URL:-}
      LLMOPS_TOKEN: ${LLMOPS_TOKEN:-}
      LLMOPS_PROJECT: rag
      LLMOPS_SERVICE: chat-api      # worker w rag-worker
      LLMOPS_ENV: production
      LLMOPS_HOST: contabo-vps
```

- [ ] **Step 9: Sprawdź, że panel kosztów w UI nadal działa**

Otwórz czat w UI RAG-a, zadaj pytanie, rozwiń panel „N wywołań · koszt · tokeny" pod odpowiedzią.

Expected: panel pokazuje wywołania jak przed zmianą. Tabela `llm_calls` RAG-a i jej powiązanie z `message_id` są nietknięte.

- [ ] **Step 10: Commit**

```bash
git add RAG/
git commit -m "feat(llmops): telemetria z czatu i workerow RAG"
```

---

### Task 6: Wpięcie kontekst-ai, Selfmadeagenta i trading-appa

Deliverable: pozostałe trzy projekty widoczne w podziale „cost by project".

**Files:**
- Modify: `kontekst ai/ai_repo/core/llm.py:87-115` (funkcja `_record`)
- Modify: `Selfmadeagent/orchestrator/agent/providers.py:11-14` (dataclass) i `:68-103` (`call_llm`)
- Modify: `trading-app/core/ollama_client.py:113-145` (`generate`), `:147-185` (`chat`), `:186-206` (`embed`)
- Test: `kontekst ai/tests/test_llmops_emission.py`
- Test: `Selfmadeagent/orchestrator/tests/test_providers_llmops.py`

**Interfaces:**
- Consumes: `llmops_client.record(...)` z Task 3.
- Produces: wiersze z `project` w `{kontekst-ai, selfmadeagent, trading-app}`. Dodatkowo `ProviderConfig` zyskuje pole `provider: str = "unknown"`.

- [ ] **Step 1: Napisz failujący test dla kontekst-ai**

Create `kontekst ai/tests/test_llmops_emission.py`:

```python
from ai_repo.core.llm import LLMClient
import ai_repo.core.llmops_client as llmops


def test_record_emits_even_without_local_db(monkeypatch):
    """kontekst-ai wychodzi wczesniej z _record, gdy nie ma self._db.
    Telemetria centralna nie moze na tym tracic."""
    sent = []
    monkeypatch.setattr(llmops, "record", lambda **kw: sent.append(kw))
    client = LLMClient(db=None, purpose="query")
    client._record("anthropic", "claude-sonnet-4-20250514", 0.0, "pytanie", "odpowiedz")
    assert len(sent) == 1
    assert sent[0]["provider"] == "anthropic"
    assert sent[0]["tokens_estimated"] is True
```

- [ ] **Step 2: Uruchom test — musi failować**

```powershell
cd "kontekst ai"
pytest tests/test_llmops_emission.py -v
```

Expected: FAIL — `assert 0 == 1` (`_record` wychodzi na `if not self._db: return`).

- [ ] **Step 3: Wepnij kontekst-ai**

Modify `kontekst ai/ai_repo/core/llm.py` — funkcja `_record` zaczyna się dziś od `if not self._db: return`. **Emisja musi trafić przed ten warunek**, inaczej jej nie będzie zawsze, gdy klient działa bez bazy:

```python
    def _record(
        self, provider: str, model: str, t0: float,
        prompt: str, result: str,
        success: bool = True, error: Optional[str] = None,
    ):
        """Record LLM call metrics if db is available."""
        import time
        latency_ms = (time.time() - t0) * 1000
        input_tokens = len(prompt) // 4
        output_tokens = len(result) // 4 if result else 0

        try:
            from ai_repo.core import llmops_client
            llmops_client.record(
                provider=provider, model=model, call_type=self._purpose,
                tokens_in=input_tokens, tokens_out=output_tokens,
                tokens_estimated=True, latency_ms=int(latency_ms),
                ok=success, error=error,
            )
        except Exception:
            pass

        if not self._db:
            return
        # ... reszta istniejacego ciala bez zmian
```

Wyliczenia `latency_ms`/`input_tokens`/`output_tokens` przenoszą się przed warunek, bo używają ich oba zapisy. Reszta istniejącego ciała zostaje nietknięta — usuń tylko zduplikowane teraz linie z `import time` i trzema przypisaniami.

- [ ] **Step 4: Uruchom testy kontekst-ai**

```powershell
cd "kontekst ai"
pytest tests/ -v
```

Expected: nowy test przechodzi, istniejące pozostają zielone.

- [ ] **Step 5: Napisz failujący test dla Selfmadeagenta**

Create `Selfmadeagent/orchestrator/tests/test_providers_llmops.py`:

```python
import pytest
from agent.providers import ProviderConfig, call_llm
import agent.llmops_client as llmops


class FakeUsage:
    prompt_tokens = 42
    completion_tokens = 13


class FakeResponse:
    usage = FakeUsage()


@pytest.mark.asyncio
async def test_successful_call_is_recorded(monkeypatch):
    sent = []
    monkeypatch.setattr(llmops, "record", lambda **kw: sent.append(kw))

    async def fake_acompletion(**kwargs):
        return FakeResponse()

    monkeypatch.setattr("agent.providers.litellm.acompletion", fake_acompletion)
    chain = [ProviderConfig(model="openrouter/qwen", provider="openrouter")]
    await call_llm([{"role": "user", "content": "hej"}], provider_chain=chain)

    assert len(sent) == 1
    assert sent[0]["provider"] == "openrouter"
    assert sent[0]["tokens_in"] == 42
    assert sent[0]["ok"] is True


@pytest.mark.asyncio
async def test_failed_provider_is_recorded_before_fallback(monkeypatch):
    sent = []
    monkeypatch.setattr(llmops, "record", lambda **kw: sent.append(kw))

    async def fake_acompletion(**kwargs):
        if kwargs["model"] == "ollama/a":
            raise RuntimeError("ollama down")
        return FakeResponse()

    monkeypatch.setattr("agent.providers.litellm.acompletion", fake_acompletion)
    chain = [ProviderConfig(model="ollama/a", provider="ollama"),
             ProviderConfig(model="openrouter/b", provider="openrouter")]
    await call_llm([{"role": "user", "content": "hej"}], provider_chain=chain)

    assert [s["ok"] for s in sent] == [False, True]
    assert sent[0]["provider"] == "ollama"
```

- [ ] **Step 6: Uruchom test — musi failować**

```powershell
cd Selfmadeagent/orchestrator
pytest tests/test_providers_llmops.py -v
```

Expected: FAIL — `TypeError: ProviderConfig.__init__() got an unexpected keyword argument 'provider'`.

- [ ] **Step 7: Wepnij Selfmadeagenta**

Modify `Selfmadeagent/orchestrator/agent/providers.py`. Najpierw dataclass:

```python
@dataclass
class ProviderConfig:
    model: str
    api_base: str | None = None
    api_key: str | None = None
    provider: str = "unknown"
```

Następnie w `get_provider_chain()` dopisz `provider=` do każdego z czterech `chain.append(ProviderConfig(...))`: `"ollama"`, `"openrouter"`, `"openai"`, `"anthropic"` — zgodnie z blokiem, w którym dany append stoi. Nazwa providera musi być jawna, bo `model` bywa prefiksowane przez LiteLLM (`ollama/...`), a bywa gołe (modele OpenAI).

Na koniec pętla w `call_llm`:

```python
    last_error = None
    for provider in provider_chain:
        t0 = time.monotonic()
        try:
            kwargs = {
                "model": provider.model,
                "messages": messages,
            }
            if provider.api_base:
                kwargs["api_base"] = provider.api_base
            if provider.api_key:
                kwargs["api_key"] = provider.api_key
            if tools:
                kwargs["tools"] = tools

            response = await litellm.acompletion(**kwargs)
            _record_llmops(provider, t0, response=response)
            return response
        except Exception as e:
            last_error = e
            _record_llmops(provider, t0, error=e)
            continue

    raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")
```

oraz funkcja pomocnicza nad `call_llm`:

```python
def _record_llmops(provider: ProviderConfig, t0: float, response=None, error=None) -> None:
    try:
        from agent import llmops_client
        usage = getattr(response, "usage", None)
        llmops_client.record(
            provider=provider.provider,
            model=provider.model,
            call_type="generate",
            tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
            tokens_out=getattr(usage, "completion_tokens", 0) or 0,
            latency_ms=int((time.monotonic() - t0) * 1000),
            ok=error is None,
            error=(str(error) if error else None),
        )
    except Exception:
        pass
```

Dopisz `import time` na górze pliku, jeśli go tam nie ma. Każda próba w łańcuchu daje osobny wiersz — inaczej fallbacki byłyby niewidoczne, a to połowa wartości panelu „error rate".

- [ ] **Step 8: Uruchom testy Selfmadeagenta**

```powershell
cd Selfmadeagent/orchestrator
pytest tests/ -v
```

Expected: nowe testy przechodzą, istniejące pozostają zielone.

- [ ] **Step 9: Wepnij trading-app**

`trading-app/tests/` jest pusty — projekt nie ma testów i **nie zakładamy tu pakietu testowego**, bo to byłoby wprowadzanie infrastruktury poza zakresem zadania. Weryfikacja jest ręczna, w Kroku 10.

Modify `trading-app/core/ollama_client.py` — w `generate()` podmień blok `try`:

```python
        try:
            data = {
                "model": model,
                "prompt": prompt,
                "stream": False
            }

            if system:
                data["system"] = system

            t0 = time.monotonic()
            response = self._ollama_request("/api/generate", data)
            self._record_llmops("ollama", model, "generate", t0,
                                response.get("prompt_eval_count", 0),
                                response.get("eval_count", 0), True, None)
            return response.get("response", "")

        except OllamaError as e:
            self._record_llmops("ollama", model, "generate", t0, 0, 0, False, str(e))
            if use_claude_fallback and self.claude_cfg.enabled:
                return self._claude_request(prompt, system)
            raise e
```

Analogicznie w `chat()` (`call_type="generate"`) i `embed()` (`call_type="embed"`, `tokens_out=0`). Dopisz `import time` na górze pliku, jeśli go nie ma, oraz metodę:

```python
    def _record_llmops(self, provider, model, call_type, t0,
                       tokens_in, tokens_out, ok, error):
        try:
            from core import llmops_client
            llmops_client.record(
                provider=provider, model=model, call_type=call_type,
                tokens_in=tokens_in or 0, tokens_out=tokens_out or 0,
                latency_ms=int((time.monotonic() - t0) * 1000),
                ok=ok, error=error,
            )
        except Exception:
            pass
```

Ollama zwraca `prompt_eval_count`/`eval_count` w odpowiedzi non-stream, więc tokeny są tu **zmierzone, nie zgadnięte** — `tokens_estimated` zostaje domyślnym `False`.

- [ ] **Step 10: Zweryfikuj wszystkie trzy projekty na żywo**

Ustaw w `.env` każdego z trzech projektów `LLMOPS_URL`, `LLMOPS_TOKEN`, `LLMOPS_PROJECT` (`kontekst-ai` / `selfmadeagent` / `trading-app`), `LLMOPS_SERVICE`, `LLMOPS_ENV=production`, `LLMOPS_HOST`. Wykonaj po jednym realnym wywołaniu w każdym, potem:

```powershell
docker exec llmops-postgres psql -U llmops -d llmops -c "SELECT project, service, provider, count(*) FROM llm_calls GROUP BY 1,2,3 ORDER BY 1"
```

Expected: widoczne wszystkie siedem projektów (`hermes` pojawia się jako `llm-proxy` — Hermes chodzi przez proxy).

- [ ] **Step 11: Commit**

```bash
git add "kontekst ai/" Selfmadeagent/ trading-app/
git commit -m "feat(llmops): telemetria z kontekst-ai, selfmadeagenta i trading-appa"
```

---

### Task 7: Dashboard w Grafanie

Deliverable: jeden ekran odpowiadający na pytania o koszt, wolumen i awarie w całej infrastrukturze.

**Files:**
- Create: `llmops/grafana/datasource-llmops.yml`
- Create: `llmops/grafana/dashboards/llm-observability.json`
- Modify: `argus/docker-compose.yml:43-46` (sekcja `volumes` usługi `grafana`)

**Interfaces:**
- Consumes: widok `v_llm_calls_costed` z Task 1, wypełniony danymi z Tasków 4–6.
- Produces: dashboard „LLM Observability" w istniejącej Grafanie na porcie 3000.

- [ ] **Step 1: Napisz datasource**

Create `llmops/grafana/datasource-llmops.yml`:

```yaml
apiVersion: 1
datasources:
  - name: llmops
    type: postgres
    uid: llmops-pg
    url: llmops-postgres:5432
    user: ${LLMOPS_DB_USER}
    secureJsonData:
      password: ${LLMOPS_DB_PASSWORD}
    jsonData:
      database: ${LLMOPS_DB_NAME}
      sslmode: disable
      postgresVersion: 1600
    isDefault: false
```

`jsonData.database` **musi** być ustawione. Brak tego pola był dokładną przyczyną „No data" przy poprzednim datasource Postgresa w tej Grafanie i nie było tego widać przez API — objaw pojawiał się dopiero w UI.

- [ ] **Step 2: Napisz zapytania dashboardu**

Panele dashboardu `llmops/grafana/dashboards/llm-observability.json` (`uid: llmops-main`, datasource `llmops-pg`, domyślny zakres `now-30d` do `now`) używają tych zapytań:

```sql
-- Panel 1 (stat): COST TODAY
SELECT COALESCE(SUM(effective_cost_usd), 0) AS "USD"
FROM v_llm_calls_costed
WHERE ts >= date_trunc('day', now());

-- Panel 2 (stat): TOKENS TODAY
SELECT COALESCE(SUM(tokens_in + tokens_out), 0) AS "tokens"
FROM v_llm_calls_costed
WHERE ts >= date_trunc('day', now());

-- Panel 3 (stat): LLM CALLS (zakres dashboardu)
SELECT count(*) AS "calls"
FROM v_llm_calls_costed
WHERE $__timeFilter(ts);

-- Panel 4 (stat, jednostka percent): ERROR RATE
SELECT COALESCE(100.0 * count(*) FILTER (WHERE NOT ok) / NULLIF(count(*), 0), 0) AS "%"
FROM v_llm_calls_costed
WHERE $__timeFilter(ts);

-- Panel 5 (timeseries): COST / DAY
SELECT date_trunc('day', ts) AS time,
       SUM(effective_cost_usd)  AS "USD"
FROM v_llm_calls_costed
WHERE $__timeFilter(ts)
GROUP BY 1 ORDER BY 1;

-- Panel 6 (bar gauge): COST BY PROJECT
SELECT project, SUM(effective_cost_usd) AS "USD"
FROM v_llm_calls_costed
WHERE $__timeFilter(ts)
GROUP BY 1 ORDER BY 2 DESC NULLS LAST;

-- Panel 7 (bar gauge): COST BY PROVIDER
SELECT provider, SUM(effective_cost_usd) AS "USD"
FROM v_llm_calls_costed
WHERE $__timeFilter(ts)
GROUP BY 1 ORDER BY 2 DESC NULLS LAST;

-- Panel 8 (table): CALLS BY MODEL
SELECT model,
       count(*)                        AS calls,
       SUM(tokens_in + tokens_out)     AS tokens,
       SUM(effective_cost_usd)         AS usd,
       ROUND(AVG(latency_ms))          AS avg_ms
FROM v_llm_calls_costed
WHERE $__timeFilter(ts)
GROUP BY 1 ORDER BY calls DESC;

-- Panel 9 (table): ERROR RATE BY PROJECT
SELECT project,
       count(*)                                  AS calls,
       count(*) FILTER (WHERE NOT ok)            AS errors,
       ROUND(100.0 * count(*) FILTER (WHERE NOT ok) / count(*), 1) AS pct
FROM v_llm_calls_costed
WHERE $__timeFilter(ts)
GROUP BY 1 ORDER BY pct DESC;

-- Panel 10 (table): WYWOLANIA BEZ CENNIKA
SELECT provider, model, count(*) AS calls,
       SUM(tokens_in + tokens_out) AS tokens
FROM v_llm_calls_costed
WHERE $__timeFilter(ts) AND pricing_missing
GROUP BY 1, 2 ORDER BY calls DESC;
```

Panel 10 nie jest ozdobą: bez niego model spoza cennika wypada z sumy kosztów po cichu i dashboard kłamie dokładnie tak, jak kłamią dziś Argus i llm-proxy.

- [ ] **Step 3: Podepnij pliki do istniejącej Grafany**

Modify `argus/docker-compose.yml` — w usłudze `grafana`, sekcja `volumes`, dopisz dwie linie:

```yaml
      - ../llmops/grafana/datasource-llmops.yml:/etc/grafana/provisioning/datasources/llmops.yml:ro
      - ../llmops/grafana/dashboards:/var/lib/grafana/dashboards/llmops:ro
```

oraz do `environment` tej usługi:

```yaml
      LLMOPS_DB_USER: ${LLMOPS_DB_USER}
      LLMOPS_DB_PASSWORD: ${LLMOPS_DB_PASSWORD}
      LLMOPS_DB_NAME: ${LLMOPS_DB_NAME}
```

Grafana musi też widzieć sieć stacku `llmops`. Sprawdź, czy `llmops-postgres` jest osiągalny po nazwie z kontenera Grafany (Krok 4); jeśli nie, w `llmops/docker-compose.yml` oznacz sieć jako zewnętrzną i podłącz do niej `grafana` w compose Argusa. Alternatywa awaryjna: w datasource użyć `${TAILSCALE_IP}:5436` zamiast nazwy kontenera.

- [ ] **Step 4: Zweryfikuj łączność i zrestartuj Grafanę**

```powershell
cd argus
docker compose up -d grafana
docker exec argus-grafana getent hosts llmops-postgres
docker compose logs grafana --tail 40
```

Expected: `getent` zwraca adres IP. Logi bez `provisioning error`.

- [ ] **Step 5: Zweryfikuj dashboard w przeglądarce**

Otwórz `http://<TAILSCALE_IP>:3000`, wejdź w dashboard „LLM Observability".

Expected: kafle pokazują liczby, nie „No data". Weryfikacja przez UI jest obowiązkowa — datasource potrafi odpowiadać poprawnie przez API i mimo to dawać „No data" na ekranie.

- [ ] **Step 6: Porównaj kafle z ręcznym SQL-em**

```powershell
docker exec llmops-postgres psql -U llmops -d llmops -c "SELECT SUM(effective_cost_usd), count(*) FROM v_llm_calls_costed WHERE ts >= date_trunc('day', now())"
```

Expected: te same liczby, co w kaflach „COST TODAY" i (przy zakresie dzisiejszym) „LLM CALLS".

- [ ] **Step 7: Commit**

```bash
git add llmops/grafana/ argus/docker-compose.yml
git commit -m "feat(llmops): dashboard obserwowalnosci LLM w grafanie"
```

---

### Task 8: Retencja, dokumentacja, runbook

Deliverable: projekt da się utrzymać bez tej rozmowy.

**Files:**
- Create: `llmops/scripts/retention.sh`
- Create: `llmops/CLAUDE.md`
- Create: `llmops/README.md`
- Modify: `CLAUDE.md` (tabela projektów w korzeniu repo)

**Interfaces:**
- Consumes: wszystko powyżej.
- Produces: dokumentacja i cron retencji.

- [ ] **Step 1: Napisz skrypt retencji**

Create `llmops/scripts/retention.sh`:

```bash
#!/usr/bin/env bash
# Kasuje wiersze starsze niz LLMOPS_RETENTION_DAYS (domyslnie 90).
set -euo pipefail
DAYS="${LLMOPS_RETENTION_DAYS:-90}"
docker exec llmops-postgres psql -U "${LLMOPS_DB_USER:-llmops}" -d "${LLMOPS_DB_NAME:-llmops}" \
  -c "DELETE FROM llm_calls WHERE ts < now() - interval '${DAYS} days'"
```

- [ ] **Step 2: Zainstaluj cron na VPS**

```bash
chmod +x /path/to/llmops/scripts/retention.sh
crontab -e
# dopisz:
0 4 * * * /path/to/llmops/scripts/retention.sh >> /var/log/llmops-retention.log 2>&1
```

- [ ] **Step 3: Napisz README z runbookiem**

Create `llmops/README.md` zawierający:
- co to jest i jaką zasadę realizuje (`llm_calls` = metryka, Langfuse = trace, Grafana = cockpit);
- uruchomienie: `docker compose up -d`, adresy (kolektor `:8090`, baza `:5436`, dashboard w Grafanie `:3000`);
- **jak dopisać model do cennika** — `INSERT INTO model_pricing ...`, z uwagą, że przy zmianie ceny dodaje się **nowy wiersz z `valid_from`**, nigdy nie edytuje starego, bo to zepsułoby historyczne koszty;
- **zadanie otwarte: zweryfikować ceny płatnych modeli** z `02-seed-pricing.sql` na stronach cenowych dostawców — liczby są przepisane z kodu tego repo i nikt ich nie potwierdził u źródła;
- jak dopiąć nowy projekt: `python client/sync_clients.py` + zmienne `LLMOPS_*` w compose;
- co robić, gdy panel „wywołania bez cennika" pokazuje wiersze (dopisać model, nie ignorować).

- [ ] **Step 4: Napisz CLAUDE.md projektu**

Create `llmops/CLAUDE.md` zgodnie z konwencją pozostałych projektów w repo: architektura, punkty wpięcia w siedmiu projektach (tabela z Tasków 4–6), konwencje (telemetria nigdy nie rzuca, zero treści, kanoniczny klient w `client/`), komendy testowe, granica etapów 1/2/3.

- [ ] **Step 5: Dopisz projekt do indeksu repo**

Modify `CLAUDE.md` w korzeniu — dodaj wiersz do tabeli „Projects":

```markdown
| **LLMOps** | `llmops/` | `llmops/CLAUDE.md` | Centralna obserwowalność wywołań LLM (koszty, tokeny, błędy) |
```

- [ ] **Step 6: Uruchom pełny zestaw testów**

```powershell
cd llmops; pytest tests/ -v
cd ../argus; pytest tests/test_llm_router.py -v
cd ../mcp-servers/llm-proxy; pytest tests/ -v
cd ../../RAG/backend; pytest tests/test_llmops_emission.py -v
cd ../../Selfmadeagent/orchestrator; pytest tests/ -v
cd "../../kontekst ai"; pytest tests/ -v
cd ../llmops; python client/sync_clients.py --check
```

Expected: wszystko zielone, `--check` kończy się kodem 0.

- [ ] **Step 7: Commit**

```bash
git add llmops/ CLAUDE.md
git commit -m "docs(llmops): retencja, runbook i CLAUDE.md projektu"
```

---

### Task 9 (opcjonalne): Backfill historii

Deliverable: cztery istniejące tabele przeniesione do centralnej, przeliczone jednym cennikiem.

Wykonać **dopiero** gdy Taski 1–8 działają na produkcji przez co najmniej tydzień i panel „wywołania bez cennika" jest pusty. Wcześniejszy backfill przeniósłby historię do tabeli, której schemat może się jeszcze zmienić.

**Files:**
- Create: `llmops/scripts/backfill.py`

- [ ] **Step 1: Napisz skrypt backfillu**

Czyta z czterech źródeł i wstawia do `llm_calls`, ustawiając `cost_usd = NULL` (żeby koszt policzył się nowym cennikiem), `tokens_estimated` zgodnie ze źródłem i `service='backfill'`:

| Źródło | DSN | Tabela | `project` | `tokens_estimated` |
|---|---|---|---|---|
| RAG | `rag-postgres:5432/rag` | `llm_calls` | `rag` | `false` |
| Argus | `argus-pg:5432/argus` | `llm_calls` | `argus` | `false` |
| llm-proxy | `PG_DSN` z env proxy | `hermes_llm_costs` | `llm-proxy` | `true` |
| kontekst-ai | DSN projektu | tabela z `record_llm_call` | `kontekst-ai` | `true` |

- [ ] **Step 2: Uruchom na sucho i porównaj sumy**

```powershell
python llmops/scripts/backfill.py --dry-run
```

Expected: wypisana liczba wierszy per źródło, zgodna z `SELECT count(*)` w źródłowych bazach.

- [ ] **Step 3: Uruchom i zweryfikuj**

```powershell
python llmops/scripts/backfill.py
docker exec llmops-postgres psql -U llmops -d llmops -c "SELECT project, service, count(*) FROM llm_calls GROUP BY 1,2 ORDER BY 1"
```

Expected: wiersze `service='backfill'` w liczbie zgodnej z krokiem 2.

- [ ] **Step 4: Commit**

```bash
git add llmops/scripts/backfill.py
git commit -m "feat(llmops): backfill historii z czterech istniejacych tabel"
```

---

## Self-Review

**Pokrycie specu:** Cel 1 (wiersz z każdego projektu) → Taski 4–6. Cel 2 (koszt z wersjonowanego cennika) → Task 1, testy `test_pricing_is_versioned_by_valid_from` i `test_missing_pricing_gives_null_not_zero`. Cel 3 (dashboard) → Task 7. Cel 4 (telemetria nie wywraca wywołania) → Task 3 (`test_collector_down_does_not_raise`, `test_full_queue_drops_without_raising`) plus osobne bloki `try` w Taskach 4–6. Kolektor, klient, retencja, „poza zakresem" — pokryte. Wymóg specu „kolektor odrzuca prompt/response" → `test_payload_with_prompt_rejected`.

**Rozbieżności ze specem, świadome i uzasadnione w sekcji „Odchylenia":** kolumna `tokens_estimated` (brak w specu), RAG jako jeden hook zamiast trzech plików, kontekst-ai jako czwarta istniejąca implementacja.

**Spójność nazw:** `record(...)` ma tę samą sygnaturę w Task 3 i we wszystkich wywołaniach w Taskach 4–6. `effective_cost_usd` i `pricing_missing` z Task 1 są używane pod tymi samymi nazwami w zapytaniach Task 7. `emit_llmops_calls` z Task 5 zgadza się z importem w teście. `ProviderConfig.provider` dodane w Task 6 Step 7 jest używane w teście z Kroku 5 tego samego zadania.

**Znane luki, wpisane wprost w kroki, nie ukryte:** dokładna nazwa funkcji w `RAG/backend/core/embeddings.py` (Task 5 Step 6 każe ją odczytać i sprawdzić podwójny zapis w Step 7); łączność sieciowa Grafany z bazą `llmops` (Task 7 Step 3 podaje warunek i dwa warianty awaryjne); brak testów w `trading-app` (Task 6 Step 9 zastępuje je weryfikacją ręczną zamiast zakładać pakiet testowy poza zakresem).
