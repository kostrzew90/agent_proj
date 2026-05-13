"""Tests for _handle_pool_monitor and _pool_bucket_ts."""
import csv
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from zoneinfo import ZoneInfo


@pytest.fixture()
def bridge(tmp_path, monkeypatch):
    """Import hermes_bridge with patched env and audit dir."""
    monkeypatch.setenv("HERMES_AUDIT_DIR", str(tmp_path))
    monkeypatch.setenv("HERMES_RECALL_DSN", "postgresql://fake:fake@localhost/fake")
    monkeypatch.setenv("HERMES_ENABLE_LEGACY_CRONS", "0")
    # Fresh import each test to pick up monkeypatched env
    sys.modules.pop("hermes_bridge", None)
    import hermes_bridge  # noqa: PLC0415
    return hermes_bridge


def _mock_response(html: str, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.text = html
    resp.status_code = status
    if status >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "err", request=MagicMock(), response=MagicMock(status_code=status)
        )
    else:
        resp.raise_for_status = MagicMock()
    return resp


GOOD_HTML = """
<div class="attendance">
  <div class="num">Aktualnie na basenie przebywa<br><span>16</span><br>osób</div>
</div>
"""

BAD_HTML = "<html><body><p>Strona w remoncie</p></body></html>"


def test_pool_monitor_success_returns_count(bridge, tmp_path):
    """Happy path: valid HTML → count returned, CSV written, Postgres called."""
    mock_conn = MagicMock()

    with patch("httpx.get", return_value=_mock_response(GOOD_HTML)), \
         patch("psycopg2.connect", return_value=mock_conn):
        result = bridge._handle_pool_monitor()

    assert "16" in result
    csv_files = list(tmp_path.glob("pool-*.csv"))
    assert len(csv_files) == 1
    rows = list(csv.reader(csv_files[0].open(encoding="utf-8")))
    assert rows[0] == ["recorded_at", "people_count", "scrape_ok", "scrape_ms", "error"]
    assert rows[1][1] == "16"
    assert rows[1][2] == "true"
    assert mock_conn.cursor.return_value.execute.called


def test_pool_monitor_parse_error_saves_html_snapshot(bridge, tmp_path):
    """Missing span → error in CSV, HTML snapshot saved to audit dir."""
    mock_conn = MagicMock()

    with patch("httpx.get", return_value=_mock_response(BAD_HTML)), \
         patch("psycopg2.connect", return_value=mock_conn):
        result = bridge._handle_pool_monitor()

    assert "błąd" in result.lower() or "error" in result.lower()
    snapshots = list(tmp_path.glob("pool_parse_error_*.html"))
    assert len(snapshots) == 1
    assert snapshots[0].read_text(encoding="utf-8") == BAD_HTML


def test_pool_monitor_network_error_retries_then_records_failure(bridge, tmp_path):
    """Network error → retries 3× with backoff, writes error row to CSV."""
    mock_conn = MagicMock()

    with patch("httpx.get", side_effect=httpx.NetworkError("timeout")), \
         patch("psycopg2.connect", return_value=mock_conn), \
         patch("time.sleep") as mock_sleep:
        result = bridge._handle_pool_monitor()

    assert mock_sleep.call_count == 2  # delays [1, 3]
    assert "błąd" in result.lower() or "error" in result.lower()
    csv_files = list(tmp_path.glob("pool-*.csv"))
    assert len(csv_files) == 1
    rows = list(csv.reader(csv_files[0].open(encoding="utf-8")))
    assert rows[1][2] == "false"
    assert rows[1][1] == ""  # people_count empty on failure


def test_pool_bucket_ts_floors_to_30min(bridge):
    """Timestamp is bucketed to the nearest 30-min floor."""
    tz = ZoneInfo("Europe/Warsaw")
    t_early = datetime(2026, 5, 13, 8, 17, 23, tzinfo=tz)   # → 08:00
    t_late  = datetime(2026, 5, 13, 8, 45, 10, tzinfo=tz)   # → 08:30
    t_exact = datetime(2026, 5, 13, 9,  0,  0, tzinfo=tz)   # → 09:00

    assert bridge._pool_bucket_ts(t_early).minute == 0
    assert bridge._pool_bucket_ts(t_early).hour == 8
    assert bridge._pool_bucket_ts(t_late).minute == 30
    assert bridge._pool_bucket_ts(t_exact).minute == 0
    assert bridge._pool_bucket_ts(t_exact).hour == 9
    assert bridge._pool_bucket_ts(t_early).second == 0
    assert bridge._pool_bucket_ts(t_early).microsecond == 0
