from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from argus.collectors.fear_greed import fetch_fear_greed, collect_fear_greed, get_current_fng
from argus.models import FearGreed


def _api(values):
    r = MagicMock()
    r.raise_for_status.return_value = None
    r.json.return_value = {"data": values, "metadata": {"error": None}}
    return r


def test_fetch_parses():
    with patch("argus.collectors.fear_greed.httpx.get",
               return_value=_api([{"value": "28", "value_classification": "Fear",
                                   "timestamp": "1794096000"}])) as g:
        rows = fetch_fear_greed(3)
    assert rows == [{"date": date(2026, 11, 8), "value": 28, "classification": "Fear"}]
    assert g.call_args.kwargs["params"] == {"limit": 3}


def _rows(n=1):
    return [{"date": date(2026, 11, 8) - timedelta(days=i), "value": 30 + i,
             "classification": "Fear"} for i in range(n)]


def test_backfill_when_empty_then_limit3(session):
    with patch("argus.collectors.fear_greed.fetch_fear_greed", return_value=_rows(2)) as f:
        assert collect_fear_greed(session) == 2
    f.assert_called_once_with(0)
    with patch("argus.collectors.fear_greed.fetch_fear_greed", return_value=_rows(2)) as f:
        collect_fear_greed(session)
    f.assert_called_once_with(3)


def test_upsert_idempotent_and_updates(session):
    with patch("argus.collectors.fear_greed.fetch_fear_greed", return_value=_rows(2)):
        collect_fear_greed(session)
        collect_fear_greed(session)
    assert session.query(FearGreed).count() == 2
    changed = _rows(1)
    changed[0]["value"] = 99
    with patch("argus.collectors.fear_greed.fetch_fear_greed", return_value=changed):
        collect_fear_greed(session)
    assert session.get(FearGreed, date(2026, 11, 8)).value == 99


def _add(session, d, v):
    session.add(FearGreed(date=d, value=v, classification="x",
                          fetched_at=datetime.now(timezone.utc)))
    session.commit()


def test_current_fng_fresh(session):
    _add(session, datetime.now(timezone.utc).date() - timedelta(days=2), 42)
    _add(session, datetime.now(timezone.utc).date() - timedelta(days=5), 10)
    assert get_current_fng(session) == 42


def test_current_fng_stale(session):
    _add(session, datetime.now(timezone.utc).date() - timedelta(days=3), 42)
    assert get_current_fng(session) is None


def test_current_fng_empty(session):
    assert get_current_fng(session) is None
