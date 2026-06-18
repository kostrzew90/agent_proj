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
