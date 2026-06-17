from unittest.mock import MagicMock, patch, call
import pytest

# ── helpers ──────────────────────────────────────────────────────────────────

def _make_conn(rows=None, description=None):
    """Return a mock psycopg2 connection whose cursor yields given rows."""
    cur = MagicMock()
    cur.fetchone.return_value = rows[0] if rows else None
    cur.description = description or [("id",), ("last_queue_depth",)]
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: cur
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cur


# ── init_db ───────────────────────────────────────────────────────────────────

@patch("db.psycopg2.connect")
def test_init_db_creates_table_and_seeds_row(mock_connect):
    conn = MagicMock()
    cur = MagicMock()
    conn.__enter__ = lambda s: conn
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.__enter__ = lambda s: cur
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_connect.return_value = conn

    import db
    db.init_db()

    executed_sqls = [c.args[0] for c in cur.execute.call_args_list]
    assert any("CREATE TABLE IF NOT EXISTS guardian_state" in sql for sql in executed_sqls)
    assert any("INSERT INTO guardian_state" in sql for sql in executed_sqls)
    conn.commit.assert_called_once()


# ── get_state ─────────────────────────────────────────────────────────────────

@patch("db.psycopg2.connect")
def test_get_state_returns_dict(mock_connect):
    conn, cur = _make_conn(
        rows=[(1, 0)],
        description=[("id",), ("last_queue_depth",)],
    )
    import db
    result = db.get_state(conn)
    assert isinstance(result, dict)
    assert result["id"] == 1
    assert result["last_queue_depth"] == 0


@patch("db.psycopg2.connect")
def test_get_state_returns_empty_dict_when_no_row(mock_connect):
    conn, cur = _make_conn(rows=[None], description=[("id",)])
    cur.fetchone.return_value = None
    import db
    result = db.get_state(conn)
    assert result == {}


# ── update_state ──────────────────────────────────────────────────────────────

@patch("db.psycopg2.connect")
def test_update_state_builds_correct_sql(mock_connect):
    conn, cur = _make_conn()
    import db
    db.update_state(conn, last_queue_depth=42, last_queue_growth_start=None)
    sql = cur.execute.call_args.args[0]
    assert "last_queue_depth = %s" in sql
    assert "last_queue_growth_start = %s" in sql
    assert "updated_at = now()" in sql
    conn.commit.assert_called_once()


@patch("db.psycopg2.connect")
def test_update_state_noop_when_no_kwargs(mock_connect):
    conn, cur = _make_conn()
    import db
    db.update_state(conn)
    cur.execute.assert_not_called()
