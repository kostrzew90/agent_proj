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
