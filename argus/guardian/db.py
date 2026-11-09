import os
import psycopg2


def get_conn():
    return psycopg2.connect(os.environ["ARGUS_DB_URL"])


def init_db():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS guardian_state (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    last_queue_depth INTEGER DEFAULT 0,
                    last_queue_growth_start TIMESTAMPTZ,
                    last_alert_container TIMESTAMPTZ,
                    last_alert_queue TIMESTAMPTZ,
                    last_alert_llm TIMESTAMPTZ,
                    last_alert_liq TIMESTAMPTZ,
                    last_alert_claims TIMESTAMPTZ,
                    last_alert_heartbeat TIMESTAMPTZ,
                    last_heartbeat_at TIMESTAMPTZ,
                    updated_at TIMESTAMPTZ DEFAULT now()
                )
            """)
            cur.execute(
                "INSERT INTO guardian_state(id) VALUES(1) ON CONFLICT DO NOTHING"
            )
        conn.commit()
    finally:
        conn.close()


def get_state(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM guardian_state WHERE id = 1")
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        return dict(zip(cols, row)) if row else {}


def update_state(conn, **kwargs):
    if not kwargs:
        return
    sets = ", ".join(f"{k} = %s" for k in kwargs)
    vals = list(kwargs.values())
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE guardian_state SET {sets}, updated_at = now() WHERE id = 1",
            vals,
        )
    conn.commit()
