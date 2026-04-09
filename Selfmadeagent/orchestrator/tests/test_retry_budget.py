from agent.retry_budget import RetryBudget


def test_fresh_budget():
    b = RetryBudget()
    assert b.can_retry()
    assert b.action_remaining == 3
    assert b.session_remaining == 15


def test_consume_action():
    b = RetryBudget()
    b.consume()
    assert b.action_remaining == 2
    assert b.session_remaining == 14


def test_action_exhausted():
    b = RetryBudget(max_per_action=2)
    b.consume()
    b.consume()
    assert not b.can_retry()


def test_reset_action():
    b = RetryBudget(max_per_action=2)
    b.consume()
    b.consume()
    assert not b.can_retry()
    b.reset_action()
    assert b.can_retry()
    assert b.session_remaining == 13


def test_session_exhausted():
    b = RetryBudget(max_per_action=100, max_per_session=3)
    b.consume()
    b.consume()
    b.consume()
    assert not b.can_retry()
    b.reset_action()
    assert not b.can_retry()  # session budget gone


def test_status():
    b = RetryBudget()
    s = b.status()
    assert "action" in s
    assert "session" in s
