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
    assert passes_gate(0.65, 6) is True


def test_passes_gate_false_low_score():
    assert passes_gate(0.55, 10) is False


def test_passes_gate_false_low_n():
    assert passes_gate(0.70, 4) is False


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
    s = compute_sizing(0.60, "BTC", "crypto")
    assert s["risk_pct"] == 0.01
    assert s["stop_pct"] == 0.05
    assert abs(s["position_pct"] - 0.20) < 1e-9
    assert s["vol_tier"] == "large"


def test_compute_sizing_stock_cap():
    # mid cap stock: risk 1%, stop 4% → 25% but capped at 15%
    s = compute_sizing(0.60, "LCID", "stock")
    assert s["position_pct"] == 0.15


def test_compute_sizing_risk_tiers():
    assert compute_sizing(0.60, "BTC", "crypto")["risk_pct"] == 0.01
    assert compute_sizing(0.76, "BTC", "crypto")["risk_pct"] == 0.02
    assert compute_sizing(0.91, "BTC", "crypto")["risk_pct"] == 0.03


# ---------------------------------------------------------------------------
# Task 4: check_whale_signals + format_signal_message
# ---------------------------------------------------------------------------
from datetime import timedelta
from argus.models import Source, SourceScore, WalletPosition, Asset
from argus.signals import check_whale_signals, format_signal_message, SignalResult


def _make_whale_source(session, handle="hl:abc", score=0.75, n=10):
    src = Source(kind="hyperliquid", handle=handle, display_name=f"HL {handle[-6:]}", active=True)
    session.add(src); session.flush()
    session.add(SourceScore(
        source_id=src.id, horizon="24h", n_claims=n,
        hit_rate=score, avg_return=0.02, decayed_score=score,
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
    src = _make_whale_source(session, handle="hl:low", score=0.50, n=10)
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
    _make_position(session, src.id, coin="DOT", opened_minutes_ago=20)
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


def _make_rss_source(session, handle, score=0.65, n=8):
    src = Source(kind="rss", handle=handle, display_name=handle, active=True)
    session.add(src); session.flush()
    session.add(SourceScore(
        source_id=src.id, horizon="24h", n_claims=n,
        hit_rate=score, avg_return=0.01, decayed_score=score,
        updated_at=datetime.now(timezone.utc),
    ))
    session.commit()
    return src


def _make_reddit_source(session, handle, score=0.65, n=8):
    src = Source(kind="reddit", handle=handle, display_name=handle, active=True)
    session.add(src); session.flush()
    session.add(SourceScore(
        source_id=src.id, horizon="24h", n_claims=n,
        hit_rate=score, avg_return=0.01, decayed_score=score,
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
    # n=5 → effective = 0.60 * (5/30) ≈ 0.10; combined(0.10, 0.10) ≈ 0.19 < 0.80
    r = _make_rss_source(session, "rss:x", score=0.60, n=5)
    rd = _make_reddit_source(session, "reddit:x", score=0.60, n=5)
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
