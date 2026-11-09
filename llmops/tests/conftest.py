import os
import psycopg2
import psycopg2.extensions
import pytest
from pathlib import Path
from dotenv import load_dotenv

# Load .env file if it exists (allows running tests without explicitly setting env vars)
env_file = Path(__file__).parent.parent / '.env'
if env_file.exists():
    load_dotenv(env_file)

# Read configuration from environment, with defaults pointing to TEST database
user = os.getenv('LLMOPS_DB_USER', 'llmops')
password = os.getenv('LLMOPS_DB_PASSWORD', 'llmopspass')
name = os.getenv('LLMOPS_TEST_DB_NAME', 'llmops_test')  # own variable: LLMOPS_DB_NAME controls production (POSTGRES_DB, collector DSN)
default_dsn = f"postgresql://{user}:{password}@127.0.0.1:5436/{name}"

DSN = os.getenv("LLMOPS_TEST_DSN", default_dsn)


@pytest.fixture
def db():
    """Realna baza — nie mock. Widok liczy koszt w Postgresie, więc testujemy Postgres.

    GUARD: This fixture ONLY runs against databases whose name ends with '_test'.
    This is the last line of defence against accidentally destroying production data.
    """
    conn = psycopg2.connect(DSN)

    # Extract database name from connection
    db_name = conn.get_dsn_parameters().get('dbname', '')

    # Guard: refuse to proceed if database is not a test database
    if not db_name.endswith('_test'):
        conn.close()
        raise RuntimeError(
            f"SAFETY GUARD: Test suite can only run against databases ending with '_test'.\n"
            f"Current database: {db_name}\n\n"
            f"Fix: Set LLMOPS_TEST_DB_NAME=llmops_test (or LLMOPS_TEST_DSN) in .env or create test DB:\n"
            f"  python3 -c \"import psycopg2; c = psycopg2.connect('host=127.0.0.1 port=5436 user=llmops password=changeme database=llmops'); "
            f"c.autocommit=True; c.cursor().execute('DROP DATABASE IF EXISTS llmops_test; CREATE DATABASE llmops_test')\"\n"
        )

    # Ensure autocommit is disabled (the default, but be explicit)
    conn.autocommit = False

    # Clean llm_calls at the START (so each test sees only its own data)
    # DO NOT delete model_pricing - it is the seeded pricing catalogue that must survive
    with conn.cursor() as cur:
        cur.execute("TRUNCATE llm_calls RESTART IDENTITY")
    conn.commit()

    yield conn
    # Rollback any test transaction (for direct-connection tests) so their inserts don't persist
    conn.rollback()
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
