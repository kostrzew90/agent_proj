"""
Standalone pool monitor — GitHub Actions / cron.
Scrapes cr.nieporet.pl and writes to Neon Postgres.
"""
import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg2
import requests
from bs4 import BeautifulSoup

URL = "https://cr.nieporet.pl/"
HEADERS = {"User-Agent": "HermesPoolMonitor/1.0"}
TZ = ZoneInfo("Europe/Warsaw")
HOURS_CSV = Path(__file__).parent.parent / "config" / "pool_hours.csv"


def bucket_ts(now: datetime) -> datetime:
    minute = 30 if now.minute >= 30 else 0
    return now.replace(minute=minute, second=0, microsecond=0)


def is_open(ts: datetime) -> bool:
    try:
        with HOURS_CSV.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if int(row["weekday"]) == ts.weekday():
                    return int(row["open"]) <= ts.hour < int(row["close"])
    except Exception:
        pass
    return 6 <= ts.hour < 22


def scrape() -> tuple[int | None, bool, int, str | None]:
    t0 = time.monotonic()
    resp = None
    error = None
    for attempt in range(3):
        try:
            resp = requests.get(URL, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            break
        except Exception as exc:
            error = str(exc)
            if attempt < 2:
                time.sleep(2 ** attempt)

    ms = int((time.monotonic() - t0) * 1000)
    if resp is None:
        return None, False, ms, error

    try:
        soup = BeautifulSoup(resp.text, "lxml")
        span = soup.select_one("div.attendance div.num span")
        if span and span.text.strip().isdigit():
            return int(span.text.strip()), True, ms, None
        error = f"selector miss: {span!r}"
    except Exception as exc:
        error = str(exc)

    return None, False, ms, error


def main() -> None:
    dsn = os.environ.get("NEON_DSN", "")
    if not dsn:
        print("ERROR: NEON_DSN not set", flush=True)
        sys.exit(1)

    ts = bucket_ts(datetime.now(tz=TZ))

    if not is_open(ts):
        print(f"Pool closed at {ts.strftime('%H:%M')} — skipping", flush=True)
        return

    count, ok, ms, error = scrape()
    print(f"Scraped: count={count} ok={ok} ms={ms} error={error}", flush=True)

    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS hermes_pool_occupancy (
                recorded_at    timestamptz PRIMARY KEY,
                people_count   int,
                scrape_ok      bool,
                scrape_ms      int,
                error          text
            )
        """)
        cur.execute("""
            INSERT INTO hermes_pool_occupancy
                (recorded_at, people_count, scrape_ok, scrape_ms, error)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (ts, count, ok, ms, error))
        print(f"Written to Neon: {ts.isoformat()}", flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
