from datetime import datetime, timedelta, timezone
import pytest
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


from unittest.mock import patch
from argus.liquidations.cascade import (
    annotate_price_context, compute_notional_p95, load_direction_rules,
    ensure_cascade_source, emit_cascade_claims,
)
from argus.models import Asset, Liquidation, Source, Claim, ClaimAudit


def _cascade(asset="BTC", side="long_liq", notional=60000.0, start_offset=0, end_offset=20):
    start = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc) + timedelta(minutes=start_offset)
    end = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc) + timedelta(minutes=end_offset)
    return CascadeEvent(asset=asset, side=side, window_start=start, window_end=end,
                         total_notional=notional, n_fills=2,
                         cascade_intensity=notional / max((end - start).total_seconds() / 60, 1.0))


def test_annotate_price_context_computes_pct_change(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True, binance_symbol="BTCUSDT"))
    session.commit()
    cascades = [_cascade()]
    with patch("argus.liquidations.cascade.get_historical_price", side_effect=[100.0, 110.0]):
        annotate_price_context(session, cascades, lookback_minutes=15)
    assert cascades[0].price_change_window == pytest.approx((110.0 - 100.0) / 100.0)


def test_annotate_price_context_leaves_none_on_price_failure(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True, binance_symbol="BTCUSDT"))
    session.commit()
    cascades = [_cascade()]
    with patch("argus.liquidations.cascade.get_historical_price", side_effect=ValueError("no data")):
        annotate_price_context(session, cascades, lookback_minutes=15)
    assert cascades[0].price_change_window is None


def test_compute_notional_p95_uses_all_history(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True))
    session.commit()
    for n in [100.0, 200.0, 300.0, 400.0, 100000.0]:
        session.add(Liquidation(asset="BTC", exchange="hyperliquid", side="long_liq",
                                 price=1.0, qty=1.0, notional_usd=n,
                                 ts=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc)))
    session.commit()
    p95 = compute_notional_p95(session)
    assert p95 > 400.0  # dominated by the 100000 outlier, not just the median cluster


def test_compute_notional_p95_empty_table_returns_zero(session):
    assert compute_notional_p95(session) == 0.0


def test_load_direction_rules_missing_file_returns_empty_dict(tmp_path):
    missing = tmp_path / "does_not_exist.yaml"
    assert load_direction_rules(str(missing)) == {}


def test_load_direction_rules_reads_yaml(tmp_path):
    f = tmp_path / "rules.yaml"
    f.write_text("direction_rule:\n  BTC: continuation\n  ETH: contrarian\n")
    assert load_direction_rules(str(f)) == {"BTC": "continuation", "ETH": "contrarian"}


def test_ensure_cascade_source_creates_once(session):
    s1 = ensure_cascade_source(session)
    s2 = ensure_cascade_source(session)
    assert s1.id == s2.id
    assert s1.kind == "derived"
    assert s1.handle == "liq-cascade"


def test_emit_cascade_claims_skips_asset_without_rule(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True, binance_symbol="BTCUSDT"))
    session.commit()
    n = emit_cascade_claims(session, [_cascade()], direction_rule={}, notional_p95=10000.0)
    assert n == 0
    assert session.query(Claim).count() == 0


def test_emit_cascade_claims_contrarian_long_liq_means_bull(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True, binance_symbol="BTCUSDT"))
    session.commit()
    with patch("argus.liquidations.cascade.get_historical_price", return_value=50000.0):
        n = emit_cascade_claims(session, [_cascade(side="long_liq")],
                                 direction_rule={"BTC": "contrarian"}, notional_p95=10000.0)
    assert n == 1
    claim = session.query(Claim).one()
    assert claim.direction == "bull"
    assert claim.entry_price == 50000.0


def test_emit_cascade_claims_continuation_long_liq_means_bear(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True, binance_symbol="BTCUSDT"))
    session.commit()
    with patch("argus.liquidations.cascade.get_historical_price", return_value=50000.0):
        n = emit_cascade_claims(session, [_cascade(side="long_liq")],
                                 direction_rule={"BTC": "continuation"}, notional_p95=10000.0)
    claim = session.query(Claim).one()
    assert claim.direction == "bear"


def test_emit_cascade_claims_entry_ts_is_window_end_not_window_start(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True, binance_symbol="BTCUSDT"))
    session.commit()
    cascade = _cascade(start_offset=0, end_offset=20)
    with patch("argus.liquidations.cascade.get_historical_price", return_value=50000.0):
        emit_cascade_claims(session, [cascade], direction_rule={"BTC": "contrarian"}, notional_p95=10000.0)
    claim = session.query(Claim).one()
    assert claim.entry_ts == cascade.window_end
    assert claim.entry_ts != cascade.window_start


def test_emit_cascade_claims_confidence_scales_with_cascade_size(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True, binance_symbol="BTCUSDT"))
    session.commit()
    small = _cascade(notional=1000.0)
    huge = _cascade(notional=1000000.0, start_offset=100, end_offset=120)
    with patch("argus.liquidations.cascade.get_historical_price", return_value=50000.0):
        emit_cascade_claims(session, [small], direction_rule={"BTC": "contrarian"}, notional_p95=10000.0)
        small_conf = session.query(Claim).one().confidence
        emit_cascade_claims(session, [huge], direction_rule={"BTC": "contrarian"}, notional_p95=10000.0)
    confs = sorted(c.confidence for c in session.query(Claim).all())
    assert confs[0] == pytest.approx(small_conf)
    assert confs[-1] > confs[0]
    assert 0.3 <= confs[0] <= 0.9
    assert 0.3 <= confs[-1] <= 0.9


def test_emit_cascade_claims_dedups_same_window(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True, binance_symbol="BTCUSDT"))
    session.commit()
    cascade = _cascade()
    with patch("argus.liquidations.cascade.get_historical_price", return_value=50000.0):
        n1 = emit_cascade_claims(session, [cascade], direction_rule={"BTC": "contrarian"}, notional_p95=10000.0)
        n2 = emit_cascade_claims(session, [cascade], direction_rule={"BTC": "contrarian"}, notional_p95=10000.0)
    assert n1 == 1
    assert n2 == 0
    assert session.query(Claim).count() == 1


def test_emit_cascade_claims_dedups_by_window_start_even_if_window_end_changes(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True, binance_symbol="BTCUSDT"))
    session.commit()
    first = _cascade(notional=60000.0, start_offset=0, end_offset=20)
    second = _cascade(notional=90000.0, start_offset=0, end_offset=35)  # same window_start, different end/notional
    with patch("argus.liquidations.cascade.get_historical_price", return_value=50000.0):
        n1 = emit_cascade_claims(session, [first], direction_rule={"BTC": "contrarian"}, notional_p95=10000.0)
        n2 = emit_cascade_claims(session, [second], direction_rule={"BTC": "contrarian"}, notional_p95=10000.0)
    assert n1 == 1
    assert n2 == 0
    assert session.query(Claim).count() == 1


def test_emit_cascade_claims_skips_on_price_failure(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True, binance_symbol="BTCUSDT"))
    session.commit()
    with patch("argus.liquidations.cascade.get_historical_price", side_effect=ValueError("no data")):
        n = emit_cascade_claims(session, [_cascade()], direction_rule={"BTC": "contrarian"}, notional_p95=10000.0)
    assert n == 0
    assert session.query(Claim).count() == 0
