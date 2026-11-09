from unittest.mock import patch
import httpx


def test_send_message_posts_to_telegram():
    """send_message should POST to Telegram API when token and chat ID are set."""
    with patch("httpx.post") as mock_post:
        import argus.telegram as tg
        orig_token, orig_chat = tg._TOKEN, tg._CHAT
        tg._TOKEN, tg._CHAT = "tok123", "chat456"
        try:
            tg.send_message("hello")
        finally:
            tg._TOKEN, tg._CHAT = orig_token, orig_chat

    mock_post.assert_called_once()
    url = mock_post.call_args.args[0]
    assert "tok123" in url
    assert mock_post.call_args.kwargs["json"]["text"] == "hello"


def test_send_message_silent_when_no_token():
    """send_message should not POST when token or chat ID is missing."""
    with patch("httpx.post") as mock_post:
        import argus.telegram as tg
        orig_token, orig_chat = tg._TOKEN, tg._CHAT
        tg._TOKEN, tg._CHAT = "", ""
        try:
            tg.send_message("hello")
        finally:
            tg._TOKEN, tg._CHAT = orig_token, orig_chat

    mock_post.assert_not_called()


def test_send_message_swallows_network_error():
    """send_message should catch and suppress network errors."""
    import argus.telegram as tg
    orig_token, orig_chat = tg._TOKEN, tg._CHAT
    tg._TOKEN, tg._CHAT = "tok", "chat"
    try:
        with patch("httpx.post", side_effect=httpx.ConnectError("fail")):
            tg.send_message("hello")  # must not raise
    finally:
        tg._TOKEN, tg._CHAT = orig_token, orig_chat


from datetime import datetime, timezone
from argus.models import SignalLog, SignalOutcome


def test_signal_log_persists(session):
    log = SignalLog(
        tier="whale",
        asset="BTC",
        direction="bull",
        source_ids="[1]",
        signal_strength=0.55,
        entry_price=67400.0,
        stop_price=64030.0,
        position_pct=0.20,
        sent_at=datetime.now(timezone.utc),
    )
    session.add(log)
    session.commit()
    assert log.id is not None


def test_signal_outcome_links_to_log(session):
    log = SignalLog(
        tier="confluence", asset="ETH", direction="bull",
        source_ids="[1,2]", signal_strength=0.84,
        entry_price=3400.0, stop_price=3230.0, position_pct=0.20,
        sent_at=datetime.now(timezone.utc),
    )
    session.add(log)
    session.flush()
    so = SignalOutcome(signal_id=log.id, asset="ETH", entry_price=3400.0, outcome="open")
    session.add(so)
    session.commit()
    assert so.id is not None
    assert so.signal_id == log.id


from argus.signals import (
    passes_gate, effective_score, combined_strength,
    vol_tier, compute_sizing,
)


def test_passes_gate_true():
    # excess = 0.65 - 0.50 = 0.15 >= 0.08 and n=6 >= 5
    assert passes_gate(0.65, 6, 0.50) is True


def test_passes_gate_false_low_score():
    # excess = 0.55 - 0.55 = 0.00 < 0.08
    assert passes_gate(0.55, 10, 0.55) is False


def test_passes_gate_false_low_n():
    # excess = 0.70 - 0.50 = 0.20 >= 0.08, but n=4 < 5
    assert passes_gate(0.70, 4, 0.50) is False


def test_passes_gate_excess_at_threshold_boundary():
    # excess exactly +0.08 with n=5 passes; +0.07 or n=4 does not.
    assert passes_gate(0.50, 5, 0.42) is True
    assert passes_gate(0.49, 5, 0.42) is False
    assert passes_gate(0.50, 4, 0.42) is False


def test_passes_gate_measures_excess_not_absolute_value():
    # High decayed_score but excess below threshold must fail: the gate
    # measures edge over cohort, not the absolute value.
    assert passes_gate(0.55, 10, 0.50) is False


def test_passes_gate_low_absolute_score_high_excess():
    # Low decayed_score still passes when its cohort baseline is even
    # lower — mirrors the real production distribution (decayed ~0.11-0.47,
    # cohort ~0.21-0.25).
    assert passes_gate(0.33, 10, 0.21) is True


def test_effective_score_full_confidence():
    assert effective_score(0.75, 30) == 0.75


def test_effective_score_partial():
    assert abs(effective_score(0.80, 15) - 0.40) < 1e-9


def test_effective_score_low_n():
    assert abs(effective_score(0.75, 5) - 0.125) < 1e-6


def test_combined_strength_two_equal():
    assert abs(combined_strength([0.6, 0.6]) - 0.84) < 1e-9


def test_combined_strength_single():
    assert combined_strength([0.7]) == 0.7


def test_combined_strength_empty():
    assert combined_strength([]) == 0.0


def test_vol_tier_large_cap():
    assert vol_tier("BTC") == "large"
    assert vol_tier("ETH") == "large"


def test_vol_tier_default_mid():
    assert vol_tier("SOL") == "mid"
    assert vol_tier("XOMA") == "mid"


def test_compute_sizing_crypto_large():
    # strength 0.20 is below the new low-tier boundary (0.35) → risk_pct 0.01
    s = compute_sizing(0.20, "BTC", "crypto")
    assert s["risk_pct"] == 0.01
    assert s["stop_pct"] == 0.05
    assert abs(s["position_pct"] - 0.20) < 1e-9
    assert s["vol_tier"] == "large"


def test_compute_sizing_stock_cap():
    # mid cap stock: risk 1%, stop 4% → 25% but capped at 15%
    s = compute_sizing(0.60, "LCID", "stock")
    assert s["position_pct"] == 0.15


def test_compute_sizing_risk_tiers():
    # Rescaled tiers post-Increment-A: <0.35 -> 0.01, >=0.35 -> 0.02, >=0.45 -> 0.03
    assert compute_sizing(0.30, "BTC", "crypto")["risk_pct"] == 0.01
    assert compute_sizing(0.40, "BTC", "crypto")["risk_pct"] == 0.02
    assert compute_sizing(0.46, "BTC", "crypto")["risk_pct"] == 0.03


# ---------------------------------------------------------------------------
# Task 4: check_whale_signals + format_signal_message
# ---------------------------------------------------------------------------
from datetime import timedelta
from argus.models import Source, SourceScore, WalletPosition, Asset
from argus.signals import check_whale_signals, format_signal_message, SignalResult


def _make_whale_source(session, handle="hl:abc", score=0.75, n=10, cohort_rate=0.22):
    src = Source(kind="hyperliquid", handle=handle, display_name=f"HL {handle[-6:]}", active=True)
    session.add(src); session.flush()
    session.add(SourceScore(
        source_id=src.id, horizon="24h", n_claims=n,
        hit_rate=score, avg_return=0.02, decayed_score=score, cohort_rate=cohort_rate,
        updated_at=datetime.now(timezone.utc),
    ))
    session.commit()
    return src


def _make_position(session, source_id, coin="BTC", side="long", entry_px=67400.0,
                   position_value=100_000.0, opened_minutes_ago=5):
    now = datetime.now(timezone.utc)
    wp = WalletPosition(
        source_id=source_id, coin=coin, side=side, szi=1.0,
        entry_px=entry_px, position_value=position_value,
        opened_ts=now - timedelta(minutes=opened_minutes_ago),
        last_seen_ts=now, open=True,
    )
    session.add(wp); session.commit()
    return wp


def test_whale_signal_generated(session):
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT",
                      scorable=True, active=True))
    session.commit()
    src = _make_whale_source(session, score=0.75, n=10)
    _make_position(session, src.id, coin="BTC", opened_minutes_ago=5)
    results = check_whale_signals(session)
    assert len(results) == 1
    assert results[0].asset == "BTC"
    assert results[0].tier == "whale"
    assert results[0].direction == "bull"


def test_whale_signal_skipped_low_score(session):
    session.add(Asset(symbol="ETH", kind="crypto", binance_symbol="ETHUSDT",
                      scorable=True, active=True))
    session.commit()
    src = _make_whale_source(session, handle="hl:low", score=0.50, n=10, cohort_rate=0.50)
    _make_position(session, src.id, coin="ETH")
    results = check_whale_signals(session)
    assert results == []


def test_whale_signal_skipped_low_n(session):
    session.add(Asset(symbol="XRP", kind="crypto", binance_symbol="XRPUSDT",
                      scorable=True, active=True))
    session.commit()
    src = _make_whale_source(session, handle="hl:lown", score=0.80, n=3)
    _make_position(session, src.id, coin="XRP")
    results = check_whale_signals(session)
    assert results == []


def test_whale_signal_skipped_old_position(session):
    session.add(Asset(symbol="DOT", kind="crypto", binance_symbol="DOTUSDT",
                      scorable=True, active=True))
    session.commit()
    src = _make_whale_source(session, handle="hl:old", score=0.75, n=10)
    _make_position(session, src.id, coin="DOT", opened_minutes_ago=25)
    results = check_whale_signals(session)
    assert results == []


def test_whale_signal_cooldown(session):
    session.add(Asset(symbol="RUNE", kind="crypto", binance_symbol="RUNEUSDT",
                      scorable=True, active=True))
    session.commit()
    src = _make_whale_source(session, handle="hl:rune", score=0.75, n=10)
    _make_position(session, src.id, coin="RUNE")
    session.add(SignalLog(
        tier="whale", asset="RUNE", direction="bull", source_ids="[1]",
        signal_strength=0.55, entry_price=1.0, stop_price=0.95,
        position_pct=0.20, sent_at=datetime.now(timezone.utc) - timedelta(hours=1),
    ))
    session.commit()
    results = check_whale_signals(session)
    assert results == []


def test_whale_signal_skipped_unknown_asset(session):
    # Reproduces the real production issue: 3 of 4 sent signals were on
    # coins outside the watchlist and could never be evaluated because
    # _last_price has no Asset row to fetch a spot price for.
    src = _make_whale_source(session, handle="hl:pons", score=0.75, n=10)
    _make_position(session, src.id, coin="PONS", opened_minutes_ago=5)
    results = check_whale_signals(session)
    assert results == []


def test_whale_signal_generated_when_asset_known(session):
    # Control: the asset-known gate does not break the happy path.
    session.add(Asset(symbol="LINK", kind="crypto", binance_symbol="LINKUSDT",
                      scorable=True, active=True))
    session.commit()
    src = _make_whale_source(session, handle="hl:link", score=0.75, n=10)
    _make_position(session, src.id, coin="LINK", opened_minutes_ago=5)
    results = check_whale_signals(session)
    assert len(results) == 1
    assert results[0].asset == "LINK"


def test_format_whale_message():
    r = SignalResult(
        tier="whale", asset="BTC", asset_kind="crypto", direction="bull",
        source_ids=[1], source_labels=["HL abc123 · 0.75 · 75%@24h · n=10"],
        signal_strength=0.125, entry_price=67400.0, stop_price=64030.0,
        position_pct=0.20, risk_pct=0.01, stop_pct=0.05,
        vol_tier="large", horizon="24h", window_str=None, whale_notional=100_000.0,
    )
    msg = format_signal_message(r)
    assert "🐋" in msg
    assert "BULLISH BTC/USDT" in msg
    assert "67400" in msg
    assert "64030" in msg
    assert "20%" in msg


def test_format_confluence_message():
    r = SignalResult(
        tier="confluence", asset="ETH", asset_kind="crypto", direction="bear",
        source_ids=[1, 2], source_labels=["src A · 0.61", "src B · 0.63"],
        signal_strength=0.84, entry_price=3400.0, stop_price=3638.0,
        position_pct=0.143, risk_pct=0.01, stop_pct=0.07,
        vol_tier="large", horizon="24h", window_str="1h45m", whale_notional=None,
    )
    msg = format_signal_message(r)
    assert "⚡" in msg
    assert "BEARISH ETH/USDT" in msg
    assert "1h45m" in msg
    assert "strength 0.84" in msg


# ---------------------------------------------------------------------------
# Task 5: check_confluence_signals
# ---------------------------------------------------------------------------
from argus.models import Claim, Price
from argus.signals import check_confluence_signals


def _make_rss_source(session, handle, score=0.65, n=8, cohort_rate=0.22):
    src = Source(kind="rss", handle=handle, display_name=handle, active=True)
    session.add(src); session.flush()
    session.add(SourceScore(
        source_id=src.id, horizon="24h", n_claims=n,
        hit_rate=score, avg_return=0.01, decayed_score=score, cohort_rate=cohort_rate,
        updated_at=datetime.now(timezone.utc),
    ))
    session.commit()
    return src


def _make_reddit_source(session, handle, score=0.65, n=8, cohort_rate=0.22):
    src = Source(kind="reddit", handle=handle, display_name=handle, active=True)
    session.add(src); session.flush()
    session.add(SourceScore(
        source_id=src.id, horizon="24h", n_claims=n,
        hit_rate=score, avg_return=0.01, decayed_score=score, cohort_rate=cohort_rate,
        updated_at=datetime.now(timezone.utc),
    ))
    session.commit()
    return src


def _make_claim(session, source_id, asset, direction="bull", minutes_ago=30):
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    c = Claim(
        source_id=source_id, asset=asset, direction=direction,
        confidence=0.7, method="rule", entry_price=100.0, entry_ts=ts, status="open",
    )
    session.add(c); session.commit()
    return c


def _make_price(session, asset, price):
    session.add(Price(asset=asset, ts=datetime.now(timezone.utc), price=price))
    session.commit()


def test_confluence_signal_generated(session):
    session.add(Asset(symbol="SOL", kind="crypto", binance_symbol="SOLUSDT",
                      scorable=True, active=True))
    session.commit()
    rss_src = _make_rss_source(session, "rss:theblock", score=0.65, n=8)
    red_src = _make_reddit_source(session, "reddit:ssb", score=0.65, n=8)
    _make_claim(session, rss_src.id, "SOL", "bull")
    _make_claim(session, red_src.id, "SOL", "bull")
    _make_price(session, "SOL", 150.0)
    results = check_confluence_signals(session)
    assert len(results) == 1
    assert results[0].asset == "SOL"
    assert results[0].tier == "confluence"


def test_confluence_skipped_same_kind(session):
    session.add(Asset(symbol="ONDO", kind="crypto", binance_symbol="ONDOUSDT",
                      scorable=True, active=True))
    session.commit()
    r1 = _make_reddit_source(session, "reddit:a", score=0.65, n=8)
    r2 = _make_reddit_source(session, "reddit:b", score=0.65, n=8)
    _make_claim(session, r1.id, "ONDO", "bull")
    _make_claim(session, r2.id, "ONDO", "bull")
    _make_price(session, "ONDO", 1.0)
    results = check_confluence_signals(session)
    assert results == []


def test_confluence_skipped_low_strength(session):
    session.add(Asset(symbol="HBAR", kind="crypto", binance_symbol="HBARUSDT",
                      scorable=True, active=True))
    session.commit()
    # Both sources clear the per-source gate (excess = 0.18 - 0.10 = 0.08,
    # n=5 >= 5), but their effective strength is low (0.18 * 5/7 ≈ 0.129
    # each), so the combined confluence strength (≈ 0.24) still falls
    # below the new _CONFLUENCE_MIN_STRENGTH floor (0.30).
    r = _make_rss_source(session, "rss:x", score=0.18, n=5, cohort_rate=0.10)
    rd = _make_reddit_source(session, "reddit:x", score=0.18, n=5, cohort_rate=0.10)
    _make_claim(session, r.id, "HBAR", "bull")
    _make_claim(session, rd.id, "HBAR", "bull")
    _make_price(session, "HBAR", 0.10)
    results = check_confluence_signals(session)
    assert results == []


def test_confluence_top3_limit(session):
    for sym, bs in [("BTC", "BTCUSDT"), ("ETH", "ETHUSDT"), ("XRP", "XRPUSDT"), ("DOT", "DOTUSDT")]:
        session.add(Asset(symbol=sym, kind="crypto", binance_symbol=bs,
                          scorable=True, active=True))
        _make_price(session, sym, 100.0)
    session.commit()
    for sym in ["BTC", "ETH", "XRP", "DOT"]:
        r = _make_rss_source(session, f"rss:{sym}", score=0.80, n=30)
        rd = _make_reddit_source(session, f"red:{sym}", score=0.80, n=30)
        _make_claim(session, r.id, sym, "bull")
        _make_claim(session, rd.id, sym, "bull")
    results = check_confluence_signals(session)
    assert len(results) <= 3


# ---------------------------------------------------------------------------
# Task 6: evaluate_signal_outcomes + send_signals
# ---------------------------------------------------------------------------
from argus.signals import evaluate_signal_outcomes, send_signals


def _make_signal_log(session, asset="BTC", direction="bull",
                     entry=67400.0, stop=64030.0, hours_ago=25):
    log = SignalLog(
        tier="whale", asset=asset, direction=direction,
        source_ids="[1]", signal_strength=0.55,
        entry_price=entry, stop_price=stop, position_pct=0.20,
        sent_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
    )
    session.add(log); session.flush()
    so = SignalOutcome(signal_id=log.id, asset=asset, entry_price=entry, outcome="open")
    session.add(so); session.commit()
    return log, so


def test_evaluate_sets_price_24h(session):
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT",
                      scorable=True, active=True))
    session.commit()
    log, so = _make_signal_log(session, hours_ago=25)
    _make_price(session, "BTC", 68000.0)
    n = evaluate_signal_outcomes(session)
    assert n == 1
    session.refresh(so)
    assert so.price_24h == 68000.0
    assert so.outcome in ("win", "loss", "open", "stopped")


def test_evaluate_marks_stopped(session):
    session.add(Asset(symbol="ETH", kind="crypto", binance_symbol="ETHUSDT",
                      scorable=True, active=True))
    session.commit()
    log, so = _make_signal_log(session, asset="ETH", direction="bull",
                               entry=3400.0, stop=3230.0, hours_ago=25)
    _make_price(session, "ETH", 3000.0)  # below stop
    evaluate_signal_outcomes(session)
    session.refresh(so)
    assert so.hit_stop is True
    assert so.outcome == "stopped"


def test_evaluate_skips_recent_signals(session):
    session.add(Asset(symbol="XRP", kind="crypto", binance_symbol="XRPUSDT",
                      scorable=True, active=True))
    session.commit()
    log, so = _make_signal_log(session, asset="XRP", hours_ago=5)
    _make_price(session, "XRP", 1.0)
    n = evaluate_signal_outcomes(session)
    assert n == 0


def test_send_signals_calls_telegram(session):
    from unittest.mock import patch
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT",
                      scorable=True, active=True))
    session.commit()
    src = _make_whale_source(session, handle="hl:send", score=0.75, n=10)
    _make_position(session, src.id, coin="BTC", opened_minutes_ago=5)
    with patch("argus.signals.send_message") as mock_send:
        send_signals(session)
    mock_send.assert_called_once()
    assert "BTC" in mock_send.call_args.args[0]


# ---------------------------------------------------------------------------
# Task 4: check_liquidation_signals (Tier 3, gated on SourceAssetScore)
# ---------------------------------------------------------------------------
from argus.models import SourceAssetScore
from argus.signals import check_liquidation_signals


def _cascade_source(session):
    src = Source(kind="derived", handle="liq-cascade", display_name="Liquidation Cascade", active=True)
    session.add(src)
    session.commit()
    return src


def _asset_score(session, source_id, asset, decayed_score, n_claims, hit_rate=0.7, horizon="24h"):
    session.add(SourceAssetScore(source_id=source_id, asset=asset, horizon=horizon,
                                  n_claims=n_claims, n_hits=int(n_claims * hit_rate),
                                  hit_rate=hit_rate, avg_return=0.02, decayed_score=decayed_score,
                                  updated_at=datetime.now(timezone.utc)))
    session.commit()


def test_liquidation_signal_fires_when_gate_passes(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True))
    session.commit()
    src = _cascade_source(session)
    _asset_score(session, src.id, "BTC", decayed_score=0.70, n_claims=6)
    session.add(Claim(source_id=src.id, asset="BTC", direction="bull", confidence=0.6,
                       method="rule", entry_price=50000.0, entry_ts=datetime.now(timezone.utc),
                       status="open"))
    session.commit()
    results = check_liquidation_signals(session)
    assert len(results) == 1
    assert results[0].tier == "liq_cascade"
    assert results[0].asset == "BTC"
    assert results[0].direction == "bull"


def test_liquidation_signal_blocked_when_gate_fails(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True))
    session.commit()
    src = _cascade_source(session)
    _asset_score(session, src.id, "BTC", decayed_score=0.40, n_claims=6)  # below 0.60 gate
    session.add(Claim(source_id=src.id, asset="BTC", direction="bull", confidence=0.6,
                       method="rule", entry_price=50000.0, entry_ts=datetime.now(timezone.utc),
                       status="open"))
    session.commit()
    assert check_liquidation_signals(session) == []


def test_liquidation_signal_ignores_stale_claims(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True))
    session.commit()
    src = _cascade_source(session)
    _asset_score(session, src.id, "BTC", decayed_score=0.70, n_claims=6)
    old_ts = datetime.now(timezone.utc) - timedelta(hours=5)
    session.add(Claim(source_id=src.id, asset="BTC", direction="bull", confidence=0.6,
                       method="rule", entry_price=50000.0, entry_ts=old_ts, status="open"))
    session.commit()
    assert check_liquidation_signals(session) == []


def test_liquidation_signal_uses_per_asset_score_not_mixed(session):
    """The key regression test for the SourceAssetScore fix: a great BTC score and a
    terrible ETH score on the SAME source must not bleed into each other."""
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True))
    session.add(Asset(symbol="ETH", kind="crypto", scorable=True))
    session.commit()
    src = _cascade_source(session)
    _asset_score(session, src.id, "BTC", decayed_score=0.80, n_claims=10)  # passes gate
    _asset_score(session, src.id, "ETH", decayed_score=0.20, n_claims=10)  # fails gate
    now = datetime.now(timezone.utc)
    session.add(Claim(source_id=src.id, asset="BTC", direction="bull", confidence=0.6,
                       method="rule", entry_price=50000.0, entry_ts=now, status="open"))
    session.add(Claim(source_id=src.id, asset="ETH", direction="bear", confidence=0.6,
                       method="rule", entry_price=3000.0, entry_ts=now, status="open"))
    session.commit()
    results = check_liquidation_signals(session)
    assert len(results) == 1
    assert results[0].asset == "BTC"


def test_liquidation_signal_respects_cooldown(session):
    session.add(Asset(symbol="BTC", kind="crypto", scorable=True))
    session.commit()
    src = _cascade_source(session)
    _asset_score(session, src.id, "BTC", decayed_score=0.70, n_claims=6)
    session.add(Claim(source_id=src.id, asset="BTC", direction="bull", confidence=0.6,
                       method="rule", entry_price=50000.0, entry_ts=datetime.now(timezone.utc),
                       status="open"))
    session.add(SignalLog(tier="liq_cascade", asset="BTC", direction="bull",
                          source_ids="[]", signal_strength=0.5, entry_price=50000.0,
                          stop_price=47500.0, position_pct=0.03,
                          sent_at=datetime.now(timezone.utc)))
    session.commit()
    assert check_liquidation_signals(session) == []


def test_format_signal_message_handles_liq_cascade_tier():
    from argus.signals import format_signal_message, SignalResult
    result = SignalResult(tier="liq_cascade", asset="BTC", asset_kind="crypto", direction="bull",
                          source_ids=[1], source_labels=["Liquidation Cascade · 0.70 · 70%@24h · n=6"],
                          signal_strength=0.5, entry_price=50000.0, stop_price=47500.0,
                          position_pct=0.03, risk_pct=0.02, stop_pct=0.05, vol_tier="large",
                          horizon="24h", window_str=None, whale_notional=None)
    msg = format_signal_message(result)
    assert "LIQUIDATION CASCADE" in msg
    assert "BTC" in msg


# ---------------------------------------------------------------------------
# Regression: _last_price falls back to live spot price when cache is empty
# ---------------------------------------------------------------------------
from argus.signals import _last_price


def test_last_price_fetches_spot_when_cache_empty(session):
    session.add(Asset(symbol="SOL", kind="crypto", binance_symbol="SOLUSDT",
                      scorable=True, active=True))
    session.commit()
    with patch("argus.signals.get_spot_price", return_value=150.0):
        price = _last_price(session, "SOL")
    assert price == 150.0
    rows = session.query(Price).all()
    assert len(rows) == 1


def test_last_price_none_when_asset_unknown(session):
    price = _last_price(session, "PONS")
    assert price is None


def test_last_price_none_when_spot_fails(session):
    session.add(Asset(symbol="SOL", kind="crypto", binance_symbol="SOLUSDT",
                      scorable=True, active=True))
    session.commit()
    with patch("argus.signals.get_spot_price", side_effect=RuntimeError("boom")):
        price = _last_price(session, "SOL")
    assert price is None


def test_confluence_signal_generated_without_price_cache(session):
    session.add(Asset(symbol="SOL", kind="crypto", binance_symbol="SOLUSDT",
                      scorable=True, active=True))
    session.commit()
    rss_src = _make_rss_source(session, "rss:theblock", score=0.65, n=8)
    red_src = _make_reddit_source(session, "reddit:ssb", score=0.65, n=8)
    _make_claim(session, rss_src.id, "SOL", "bull")
    _make_claim(session, red_src.id, "SOL", "bull")
    with patch("argus.signals.get_spot_price", return_value=150.0):
        results = check_confluence_signals(session)
    assert len(results) == 1
    assert results[0].asset == "SOL"
    assert results[0].tier == "confluence"


# ---------------------------------------------------------------------------
# Fear & Greed
# ---------------------------------------------------------------------------
from argus.signals import SignalResult, apply_fear_greed, format_signal_message


def _fng_result(direction="bull", kind="crypto"):
    return SignalResult(
        tier="whale", asset="BTC", asset_kind=kind, direction=direction,
        source_ids=[1], source_labels=["x"], signal_strength=0.5, entry_price=100.0,
        stop_price=95.0, position_pct=0.4, risk_pct=0.02, stop_pct=0.05,
        vol_tier="large", horizon="24h", window_str=None, whale_notional=None)


def test_fng_extreme_greed_bull_halves():
    r = apply_fear_greed(_fng_result("bull"), 80)
    assert (r.position_pct, r.risk_pct, r.fng_adjusted, r.fng_value) == (0.2, 0.01, True, 80)


def test_fng_neutral_bull_unchanged():
    r = apply_fear_greed(_fng_result("bull"), 50)
    assert (r.position_pct, r.risk_pct, r.fng_adjusted, r.fng_value) == (0.4, 0.02, False, 50)


def test_fng_extreme_fear_bear_halves():
    r = apply_fear_greed(_fng_result("bear"), 20)
    assert (r.position_pct, r.fng_adjusted) == (0.2, True)


def test_fng_extreme_fear_bull_unchanged():
    r = apply_fear_greed(_fng_result("bull"), 20)
    assert (r.position_pct, r.fng_adjusted) == (0.4, False)


def test_fng_none_unchanged():
    r = apply_fear_greed(_fng_result("bull"), None)
    assert (r.position_pct, r.fng_value, r.fng_adjusted) == (0.4, None, False)


def test_fng_stock_untouched():
    r = apply_fear_greed(_fng_result("bull", kind="stock"), 80)
    assert (r.position_pct, r.fng_value, r.fng_adjusted) == (0.4, None, False)


def test_message_contains_fng_lines():
    r = apply_fear_greed(_fng_result("bull"), 80)
    msg = format_signal_message(r)
    assert "Fear & Greed: 80 (skrajna chciwość)" in msg
    assert "pozycja zmniejszona o połowę" in msg
    assert "Pozycja: 20% portfela" in msg


def test_message_without_fng_has_no_line():
    assert "Fear & Greed" not in format_signal_message(_fng_result())


def _setup_whale(session):
    session.add(Asset(symbol="BTC", kind="crypto", binance_symbol="BTCUSDT",
                      scorable=True, active=True))
    session.commit()
    src = _make_whale_source(session, handle="hl:fng", score=0.75, n=10)
    _make_position(session, src.id, coin="BTC", opened_minutes_ago=5)


def test_send_signals_saves_fng_value(session):
    _setup_whale(session)
    with patch("argus.signals.send_message") as m, \
         patch("argus.collectors.fear_greed.get_current_fng", return_value=80):
        send_signals(session)
    assert "Fear & Greed: 80" in m.call_args.args[0]
    assert session.query(SignalLog).one().fng_value == 80


def test_send_signals_survives_fng_failure(session):
    _setup_whale(session)
    with patch("argus.signals.send_message") as m, \
         patch("argus.collectors.fear_greed.get_current_fng", side_effect=RuntimeError("db")):
        send_signals(session)
    m.assert_called_once()
    assert session.query(SignalLog).one().fng_value is None
