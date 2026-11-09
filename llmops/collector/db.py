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
        result = len(rows)
    except Exception:
        pool.putconn(conn, close=True)
        raise
    else:
        pool.putconn(conn)
        return result


def ping() -> None:
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception:
        pool.putconn(conn, close=True)
        raise
    else:
        pool.putconn(conn)
