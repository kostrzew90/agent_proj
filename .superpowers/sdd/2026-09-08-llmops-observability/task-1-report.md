# Task 1 Implementation Report: llmops Database Layer

**Commit SHA:** `31f66c01d2fc73034467ead5d924e9e418bc3141`

**Status:** BLOCKED (Docker daemon not running)

## Summary

All files for Task 1 have been created according to the brief specification. Database schema, initial pricing seed, Docker Compose stack, and comprehensive test suite are in place. Implementation is complete and ready for testing once Docker daemon becomes available.

## Files Created

The following files were created in the `llmops/` directory:

### Core Infrastructure
- `llmops/docker-compose.yml` — PostgreSQL 16 Alpine service definition with health checks, port binding to TAILSCALE_IP (127.0.0.1), persistent volume
- `llmops/.env.example` — Environment configuration template with default credentials
- `llmops/.env` — Copied from .env.example for docker-compose
- `llmops/requirements-dev.txt` — Python test dependencies (pytest 8.3.*, psycopg2-binary 2.9.*, httpx 0.27.*)

### Database Layer
- `llmops/db-init/01-schema.sql` — Complete schema with:
  - `llm_calls` table (18 columns) capturing all LLM call metadata
  - Three performance indexes on `ts`, `project+ts`, `model+ts`
  - `model_pricing` table with versioned pricing by `valid_from` timestamp
  - `v_llm_calls_costed` view that derives `effective_cost_usd` and `pricing_missing` flag

- `llmops/db-init/02-seed-pricing.sql` — Initial pricing data with:
  - 9 models across 4 providers (ollama, groq, gemini, openrouter)
  - Mix of free models (0.0 USD/Mtok) and paid (e.g., gpt-4o-mini at 0.15/0.60)
  - Ollama marked with wildcard 'ANY' as placeholder (exact models tracked via missing pricing)

### Test Suite
- `llmops/tests/__init__.py` — Package marker for pytest discovery
- `llmops/tests/conftest.py` — Test fixtures:
  - `db` fixture: connects to real Postgres at DSN (default: `postgresql://llmops:llmopspass@127.0.0.1:5436/llmops`)
  - `insert_call()` helper: inserts test LLM call records with sensible defaults
  - Fixture cleans tables between test runs (TRUNCATE llm_calls, DELETE from model_pricing)

- `llmops/tests/test_schema.py` — 5 acceptance tests:
  1. `test_cost_computed_from_pricing` — Verifies view calculates cost from pricing table when no explicit cost
  2. `test_missing_pricing_gives_null_not_zero` — **KEY TEST** — Ensures unknown models return NULL, not 0 (prevents silent cost loss)
  3. `test_explicit_cost_wins_over_pricing` — Explicit cost_usd column takes precedence over calculated cost
  4. `test_pricing_is_versioned_by_valid_from` — Pricing applied based on valid_from timestamp relative to call timestamp
  5. `test_free_model_is_zero_not_null` — Free models (0.0 pricing) correctly compute to 0, not NULL

## Critical Design: NULL vs 0 for Missing Pricing

The view SQL implements the key requirement:
```sql
COALESCE(
    c.cost_usd,
    p.usd_per_mtok_in  * c.tokens_in  / 1e6
  + p.usd_per_mtok_out * c.tokens_out / 1e6
)                                        AS effective_cost_usd,
```

- If `cost_usd` is NULL and pricing row `p` exists: calculates cost
- If `cost_usd` is NULL and pricing row `p` is NULL: returns NULL (the sentinel value for "missing pricing")
- If `cost_usd` is provided: uses explicit cost (pricing ignored)

The `pricing_missing` flag:
```sql
(c.cost_usd IS NULL AND p.id IS NULL)    AS pricing_missing
```

Signals when a call has no cost and no pricing found — this is observable to downstream systems (e.g., for alerting).

## Test Execution

### Attempt 1: Initial Run (Expected to Fail)
```bash
cd llmops && pytest tests/test_schema.py -v
```

**Issue:** Import error — pytest found parent conftest.py in `C:\Users\DAMA\Documents\docker\n8n\`, masking the tests/conftest.py.

**Fix Applied:** Changed test import from `from conftest import insert_call` to `from .conftest import insert_call` (relative import).

### Attempt 2: After Import Fix
```bash
cd llmops && pytest tests/test_schema.py -v
```

**Result:** 5 errors in test setup, all identical:
```
psycopg2.OperationalError: connection to server at "127.0.0.1", port 5436 failed: Connection refused (0x0000274D/10061)
Is the server running on that host and accepting TCP/IP connections?
```

### Docker Daemon Status

Attempted 5 retries (each 3 seconds apart):
```bash
docker compose up -d
```

**All failed:** `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine; ... Nie można odnaleźć określonego pliku.`

(Polish error message: "The specified file cannot be found" — Docker Desktop pipe not available on this Windows 11 Pro system.)

## Blockers

1. **Docker Desktop not running** — No Docker daemon accessible on Windows host
2. **No workarounds taken** — Per brief, did not switch to SQLite, did not mock psycopg2, did not create in-memory database
3. **Tests accurately capture real failure** — pytest collects 5 tests but all fail at fixture setup with valid psycopg2 error

## Deviations from Brief

Two intentional deviations made to fix technical issues:

1. **Relative import in test file** — Brief specified `from conftest import insert_call`, but pytest discovered a parent-directory conftest.py (C:\Users\DAMA\Documents\docker\n8n\conftest.py) that masked the intended local conftest. Changed to `from .conftest import insert_call` (relative import) to resolve the fixture correctly. This is a pytest best practice.

2. **Added `llmops/tests/__init__.py`** — Not in the brief's file list, but required for pytest to treat tests/ as a package and enable relative imports. Standard Python convention.

## Expected Behavior (Once Docker Runs)

Once Docker daemon becomes available and stack is running:

1. `docker compose up -d` will start `llmops-postgres:5436`
2. `/docker-entrypoint-initdb.d/` will run `01-schema.sql` and `02-seed-pricing.sql` automatically
3. `pytest tests/test_schema.py -v` should output:

   ```
   test_cost_computed_from_pricing PASSED
   test_missing_pricing_gives_null_not_zero PASSED
   test_explicit_cost_wins_over_pricing PASSED
   test_pricing_is_versioned_by_valid_from PASSED
   test_free_model_is_zero_not_null PASSED

   ===== 5 passed in X.XXs =====
   ```

## Post-Review Fixes Applied

**Fix #1 — Honest deviation reporting:** Section "Deviations from Brief" corrected to disclose two intentional changes (relative import + __init__.py) that were necessary for pytest fixture resolution. Original claim of "None" was contradicted by the immediately following explanation and has been replaced with truthful documentation.

**Fix #2 — Timestamp literal safety:** The test `test_pricing_is_versioned_by_valid_from` uses bare date+Z format (`'2020-01-01Z'`, `'2030-01-01Z'`, `'2025-01-01Z'`) which may not parse unambiguously in Postgres's timestamptz parser. Replaced all three with full ISO-8601 format: `'2020-01-01T00:00:00Z'`, `'2030-01-01T00:00:00Z'`, `'2025-01-01T00:00:00Z'`. This removes parser ambiguity and ensures the versioning test validates the actual requirement (historical pricing correctness) rather than failing on a parse error.

**Test execution status:** Docker daemon remains unavailable. Both fixes are code-level and require no database interaction to validate. Once Docker is running, `pytest tests/test_schema.py -v` will test both fixes.

## Next Steps (Unblocked Once Docker Available)

1. Start Docker Desktop
2. Navigate to llmops/
3. Run: `docker compose up -d && docker compose ps`
4. Wait for healthcheck to show healthy
5. Run: `pytest tests/test_schema.py -v`
6. Verify: 5 passed
7. Task 1 complete

## Notes

- No environment secrets exposed in repository (.env is git-ignored, only .env.example is tracked)
- Postgres defaults are safe for local testing
- View performance is optimal for telemetry volume via LEFT JOIN LATERAL (early-terminating subquery)
- Pricing table UNIQUE constraint on (provider, model, valid_from) prevents duplicates
- `tokens_estimated` boolean flag available for future optimization of estimated-token handling

---

## Post-Coordinator Review Fix: Credential Mismatch

**Issue Discovered:** The documented fresh-checkout sequence failed on a real Postgres stack:
- `.env.example` sets `LLMOPS_DB_PASSWORD=changeme`
- `tests/conftest.py` hardcoded `DSN = "...llmopspass@..."` 
- When a user ran `cp .env.example .env && docker compose up -d && pytest tests/test_schema.py`, docker would use password `changeme` but conftest would try `llmopspass`, causing `FATAL: password authentication failed for user "llmops"` (exit code 1, 0.22s)

**Root Cause:** The test fixture was not following the configuration — it had its own hardcoded defaults instead of reading from the same environment variables that docker-compose consumes.

**Fix Applied:**

1. **Modified `tests/conftest.py`** to read configuration from environment:
   ```python
   from dotenv import load_dotenv
   from pathlib import Path
   
   # Load .env file if it exists
   env_file = Path(__file__).parent.parent / '.env'
   if env_file.exists():
       load_dotenv(env_file)
   
   # Read from environment with defaults matching docker-compose
   user = os.getenv('LLMOPS_DB_USER', 'llmops')
   password = os.getenv('LLMOPS_DB_PASSWORD', 'llmopspass')
   name = os.getenv('LLMOPS_DB_NAME', 'llmops')
   default_dsn = f"postgresql://{user}:{password}@127.0.0.1:5436/{name}"
   
   DSN = os.getenv("LLMOPS_TEST_DSN", default_dsn)
   ```

   - Loads `.env` using `python-dotenv` (already available in environment)
   - Reads `LLMOPS_DB_USER`, `LLMOPS_DB_PASSWORD`, `LLMOPS_DB_NAME` from environment
   - Uses defaults (`llmops`, `llmopspass`, `llmops`) matching docker-compose's hardcoded defaults
   - Honors explicit `LLMOPS_TEST_DSN` override if set
   - When `.env` is in place (from `cp .env.example .env`), conftest now uses the same credentials as docker-compose

2. **Created `llmops/.gitignore`** to prevent `.env` from being committed:
   ```
   .env
   ```
   (Only `.env.example` is tracked in git as the template.)

**Test Verification (Fresh Path):**

With `.env` in place and docker compose stack running, tests now pass without LLMOPS_TEST_DSN override:

```
pytest tests/test_schema.py -v

============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-8.3.5, pluggy-1.6.0
collected 5 items

tests\test_schema.py::test_cost_computed_from_pricing PASSED             [ 20%]
tests\test_schema.py::test_missing_pricing_gives_null_not_zero PASSED    [ 40%]
tests\test_schema.py::test_explicit_cost_wins_over_pricing PASSED        [ 60%]
tests\test_schema.py::test_pricing_is_versioned_by_valid_from PASSED     [ 80%]
tests\test_schema.py::test_free_model_is_zero_not_null PASSED            [100%]

============================== 5 passed in 0.25s ==============================
```

**Fresh-Checkout Path Now Works:**
```bash
cd llmops/
cp .env.example .env
docker compose up -d
docker compose ps
pytest tests/test_schema.py -v  # No LLMOPS_TEST_DSN needed
# Result: 5 passed ✓
```

**Backward Compatibility:** Explicit `LLMOPS_TEST_DSN` overrides still work and take precedence, allowing CI/CD to point tests at external databases if needed.


---

## Post-Coordinator Verification Fix: Missing Dependency

**Issue Discovered:** The credential fix introduced a regression — `tests/conftest.py` imports `python-dotenv` at the top level (line 5), but `python-dotenv` is not declared in `llmops/requirements-dev.txt`. On a clean checkout with `pip install -r requirements-dev.txt`, pytest fails at collection time with:
```
ModuleNotFoundError: No module named 'dotenv'
```

This masks the entire test suite as broken, a worse UX than the original password mismatch error.

**Root Cause:** Dependency was used without being declared. It worked on the test host only because it happened to be pre-installed.

**Fix Applied:**

Added `python-dotenv==1.2.*` to `llmops/requirements-dev.txt`, pinned in the same `==X.Y.*` style as its neighbors:
```
pytest==8.3.*
psycopg2-binary==2.9.*
httpx==0.27.*
python-dotenv==1.2.*
```

**Why not remove the dependency instead?** The code deliberately uses different defaults:
- `conftest.py` defaults to `llmopspass` (matching docker-compose's hardcoded defaults)
- `.env.example` ships with `changeme` (meant to be replaced in production)

Reading `.env` dynamically is what makes the fresh-checkout path work without manual environment variable export. Removing `python-dotenv` would reintroduce the original credential mismatch bug in disguise.

**Test Verification (Post-Fix):**
```
pytest tests/test_schema.py -v

============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-8.3.5, pluggy-1.6.0
collected 5 items

tests\test_schema.py::test_cost_computed_from_pricing PASSED             [ 20%]
tests\test_schema.py::test_missing_pricing_gives_null_not_zero PASSED    [ 40%]
tests\test_schema.py::test_explicit_cost_wins_over_pricing PASSED        [ 60%]
tests\test_schema.py::test_pricing_is_versioned_by_valid_from PASSED     [ 80%]
tests\test_schema.py::test_free_model_is_zero_not_null PASSED            [100%]

============================== 5 passed in 0.27s ==============================
```

**Fresh-Checkout Path Verified:**
```bash
cd llmops/
pip install -r requirements-dev.txt  # Now includes python-dotenv
cp .env.example .env
docker compose up -d
pytest tests/test_schema.py -v  # No LLMOPS_TEST_DSN needed
# Result: 5 passed ✓ (collection succeeds, tests pass with correct credentials)
```

**Task 1 Complete:** All acceptance tests pass. Schema, view, pricing table, and test suite are correct. Fresh-checkout path is unbroken. Credentials are not leaked to git.



---

## Critical Fix: Test Fixture Data Loss

**Issue Discovered:** The `db` fixture was deleting the entire `model_pricing` table before each test. This table is the seeded pricing catalogue that the system depends on. After running tests, the catalogue was empty, so all subsequent calls had NULL costs instead of calculated costs.

**Impact:** Tests would silently wipe the pricing catalogue, causing every new call logged to have unmeasurable cost (NULL), losing the exact data the system was designed to protect.

**Fix Applied:**

Modified `llmops/tests/conftest.py` to:
1. **TRUNCATE llm_calls** at START of each test (fresh test data)
2. **NEVER touch model_pricing** (preserve seeded catalogue)  
3. **ROLLBACK test transaction at teardown**

**Test Adjustments:**

Schema tests now filter queries by model name to avoid reading previous tests' data.

**Verification:**

Model pricing count BEFORE tests:  10
Full test suite: 21 passed
Model pricing count AFTER tests:   10

============================= 21 passed in 6.92s ==============================

The seeded catalogue (10 rows) is completely intact before and after the full test suite runs.


---

## Final Fix: Test Database Isolation with Safety Guard

**Problem:** TRUNCATE llm_calls persists. Transactions cannot fix this because collector tests use HTTP APIs with separate connections. The solution is structural isolation.

**Solution Implemented:**

1. **Dedicated Test Database llmops_test**
   - Created separate Postgres database for testing
   - Initialized with schema and seed data
   - Isolated from production llmops

2. **Safety Guard in Fixture**
   - Checks database name at connection time
   - Refuses to proceed if name does not end with _test
   - No environment variable bypass
   - Clear error message with remediation

3. **Default Points to Test Database**
   - Fixture defaults to llmops_test, not llmops
   - Production protected by database name check

**How Isolation Works:**

- Collector tests via HTTP API: writes to llmops_test, TRUNCATE happens in llmops_test, production llmops untouched
- Schema tests via fixture: rollback at teardown
- Result: destructive but confined to llmops_test

**Canary Test Verification:**

Test row inserted into REAL llmops:
- Canary rows in llmops BEFORE tests: 1
- Canary rows in llmops AFTER tests: 1
- Model pricing in llmops: 10

**Guard Behavior:**

When LLMOPS_TEST_DSN points to production (database=llmops):

RuntimeError: SAFETY GUARD: Test suite can only run against databases ending with '_test'.
Current database: llmops

Guard blocks accidental runs. Clear, non-bypassable.

**Verification:**

1. Full suite schema tests: 5 passed
2. Canary survived in llmops: 1 row before and after
3. Production pricing intact: 10 rows
4. Guard rejects production: RuntimeError raised

Test suite now impossible to accidentally run against production.
Pricing catalogue in production structurally protected.
