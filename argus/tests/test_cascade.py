from datetime import datetime, timedelta, timezone
from argus.liquidations.cascade import CascadeEvent, detect_cascades


def _liq(asset="BTC", side="long_liq", notional=10000.0, minutes_offset=0):
    class _Row:
        pass
    r = _Row()
    r.asset = asset
    r.side = side
    r.notional_usd = notional
    r.ts = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes_offset)
    return r


def test_empty_input_returns_no_cascades():
    assert detect_cascades([], window_minutes=30, min_notional=50000) == []


def test_single_fill_below_threshold_is_not_a_cascade():
    liqs = [_liq(notional=1000.0)]
    assert detect_cascades(liqs, window_minutes=30, min_notional=50000) == []


def test_fills_within_window_cluster_into_one_cascade():
    liqs = [
        _liq(notional=20000.0, minutes_offset=0),
        _liq(notional=20000.0, minutes_offset=10),
        _liq(notional=20000.0, minutes_offset=20),
    ]
    result = detect_cascades(liqs, window_minutes=30, min_notional=50000)
    assert len(result) == 1
    c = result[0]
    assert c.asset == "BTC"
    assert c.side == "long_liq"
    assert c.total_notional == 60000.0
    assert c.n_fills == 3
    assert c.window_start == datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    assert c.window_end == datetime(2026, 1, 1, 10, 20, tzinfo=timezone.utc)


def test_gap_beyond_window_starts_new_cluster_no_overlap_spam():
    liqs = [
        _liq(notional=30000.0, minutes_offset=0),
        _liq(notional=30000.0, minutes_offset=10),
        _liq(notional=30000.0, minutes_offset=200),  # far beyond 30min window
        _liq(notional=30000.0, minutes_offset=210),
    ]
    result = detect_cascades(liqs, window_minutes=30, min_notional=50000)
    assert len(result) == 2
    assert result[0].total_notional == 60000.0
    assert result[1].total_notional == 60000.0


def test_different_asset_and_side_tracked_independently():
    liqs = [
        _liq(asset="BTC", side="long_liq", notional=60000.0, minutes_offset=0),
        _liq(asset="BTC", side="short_liq", notional=60000.0, minutes_offset=0),
        _liq(asset="ETH", side="long_liq", notional=60000.0, minutes_offset=0),
    ]
    result = detect_cascades(liqs, window_minutes=30, min_notional=50000)
    keys = {(c.asset, c.side) for c in result}
    assert keys == {("BTC", "long_liq"), ("BTC", "short_liq"), ("ETH", "long_liq")}


def test_cascade_intensity_is_notional_over_duration_minutes():
    liqs = [
        _liq(notional=30000.0, minutes_offset=0),
        _liq(notional=30000.0, minutes_offset=20),
    ]
    result = detect_cascades(liqs, window_minutes=30, min_notional=50000)
    assert len(result) == 1
    assert result[0].cascade_intensity == 60000.0 / 20


def test_single_fill_cascade_intensity_uses_minimum_duration_floor():
    liqs = [_liq(notional=60000.0, minutes_offset=0)]
    result = detect_cascades(liqs, window_minutes=30, min_notional=50000)
    assert len(result) == 1
    # duration floor of 1 minute avoids division by zero
    assert result[0].cascade_intensity == 60000.0 / 1.0


def test_price_change_window_defaults_to_none():
    liqs = [_liq(notional=60000.0)]
    result = detect_cascades(liqs, window_minutes=30, min_notional=50000)
    assert result[0].price_change_window is None
