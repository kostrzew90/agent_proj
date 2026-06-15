"""TDD tests for FRED macro data collector."""
from datetime import date
from unittest.mock import patch, MagicMock
import pytest

from argus.collectors.fred import (
    SERIES,
    parse_observations,
    collect_fred,
    get_latest_macro,
)


# ── sample FRED API responses ─────────────────────────────────────────────────

_OBSERVATIONS_OK = {
    "observations": [
        {"date": "2026-06-01", "value": "4.33"},
        {"date": "2026-05-01", "value": "4.33"},
        {"date": "2026-04-01", "value": "4.50"},
        {"date": "2026-03-01", "value": "."},   # not yet published
    ]
}

_OBSERVATIONS_EMPTY = {"observations": []}


# ── unit: parse_observations ──────────────────────────────────────────────────

def test_parse_filters_missing_values():
    rows = parse_observations("FEDFUNDS", _OBSERVATIONS_OK)
    assert len(rows) == 3   # "." excluded

def test_parse_fields():
    rows = parse_observations("FEDFUNDS", _OBSERVATIONS_OK)
    assert rows[0] == {"series_id": "FEDFUNDS", "date": date(2026, 6, 1), "value": 4.33}

def test_parse_sorted_newest_first():
    rows = parse_observations("FEDFUNDS", _OBSERVATIONS_OK)
    assert rows[0]["date"] > rows[1]["date"]

def test_parse_empty():
    rows = parse_observations("FEDFUNDS", _OBSERVATIONS_EMPTY)
    assert rows == []

def test_series_map_nonempty():
    assert len(SERIES) >= 4
    assert "DFF" in SERIES
    assert "T10Y2Y" in SERIES


# ── unit: collect_fred ────────────────────────────────────────────────────────

def _make_session(existing=False):
    s = MagicMock()
    s.scalar.return_value = MagicMock() if existing else None
    s.flush = MagicMock()
    s.commit = MagicMock()
    return s


def _mock_fetch(series_id, api_key, lookback=12):
    return [
        {"series_id": series_id, "date": date(2026, 6, 1), "value": 4.33},
        {"series_id": series_id, "date": date(2026, 5, 1), "value": 4.50},
    ]


def test_collect_inserts_new_rows():
    session = _make_session(existing=False)
    with patch("argus.collectors.fred.fetch_series", side_effect=_mock_fetch):
        stats = collect_fred(session, api_key="testkey", lookback=3)
    assert stats["inserted"] > 0
    session.commit.assert_called()


def test_collect_skips_existing():
    session = _make_session(existing=True)
    with patch("argus.collectors.fred.fetch_series", side_effect=_mock_fetch):
        stats = collect_fred(session, api_key="testkey", lookback=3)
    assert stats["inserted"] == 0
    assert stats["skipped"] > 0


def test_collect_handles_fetch_error():
    session = _make_session()
    with patch("argus.collectors.fred.fetch_series", side_effect=Exception("timeout")):
        stats = collect_fred(session, api_key="testkey", lookback=3)
    assert stats["errors"] > 0
    assert stats["inserted"] == 0


# ── unit: get_latest_macro ────────────────────────────────────────────────────

def test_get_latest_macro_returns_dict():
    session = MagicMock()
    # simulate DB rows
    rows = [
        MagicMock(series_id="DFF",     obs_date=date(2026,6,14), value=4.33),
        MagicMock(series_id="T10Y2Y",  obs_date=date(2026,6,14), value=0.15),
        MagicMock(series_id="M2SL",    obs_date=date(2026,5,1),  value=21500.0),
        MagicMock(series_id="CPIAUCSL",obs_date=date(2026,5,1),  value=315.2),
    ]
    session.execute.return_value.fetchall.return_value = rows
    result = get_latest_macro(session)
    assert "DFF" in result
    assert result["DFF"]["value"] == 4.33
    assert result["T10Y2Y"]["value"] == 0.15
