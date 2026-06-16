from datetime import datetime, timezone
from argus.models import LlmQueue

def test_llm_queue_model_exists(session):
    now = datetime.now(timezone.utc)
    entry = LlmQueue(
        item_id=1,
        text_hash="abc123",
        source_kind="reddit",
        status="pending",
        attempts=0,
        enqueued_at=now,
    )
    session.add(entry)
    session.commit()
    row = session.query(LlmQueue).one()
    assert row.text_hash == "abc123"
    assert row.source_kind == "reddit"
    assert row.status == "pending"
    assert row.attempts == 0
    assert row.processed_at is None
    assert row.last_error is None
