from datetime import datetime, timezone, timedelta

from tresrv.domain.daytime import local_date, resolve_consumed_at, WARSAW


def test_local_date_converts_utc_to_warsaw_date():
    dt = datetime(2026, 8, 23, 22, 30, tzinfo=timezone.utc)  # 00:30 next day in Warsaw (CEST, UTC+2)
    assert local_date(dt) == datetime(2026, 8, 24).date()


def test_resolve_consumed_at_none_hint_returns_logged_at():
    logged_at = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    consumed_at, needs_confirm = resolve_consumed_at(logged_at, None)
    assert consumed_at == logged_at
    assert needs_confirm is False


def test_resolve_consumed_at_hours_ago_hint():
    logged_at = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    consumed_at, needs_confirm = resolve_consumed_at(logged_at, "3h_ago")
    assert consumed_at == logged_at - timedelta(hours=3)
    assert needs_confirm is False


def test_resolve_consumed_at_yesterday_hint():
    logged_at = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    consumed_at, needs_confirm = resolve_consumed_at(logged_at, "yesterday")
    assert consumed_at == logged_at - timedelta(days=1)
    assert needs_confirm is False


def test_resolve_consumed_at_unknown_hint_falls_back_to_logged_at():
    logged_at = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    consumed_at, needs_confirm = resolve_consumed_at(logged_at, "some_garbage")
    assert consumed_at == logged_at
    assert needs_confirm is False


def test_resolve_consumed_at_beyond_48h_needs_confirmation():
    logged_at = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    consumed_at, needs_confirm = resolve_consumed_at(logged_at, "72h_ago")
    assert consumed_at == logged_at - timedelta(hours=72)
    assert needs_confirm is True
