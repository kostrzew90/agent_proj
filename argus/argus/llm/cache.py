import hashlib
from datetime import datetime, timezone
from argus.models import LlmCache

def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def cache_get(session, h: str):
    row = session.get(LlmCache, h)
    return row.result_json if row is not None else None

def cache_put(session, h: str, result: list) -> None:
    if session.get(LlmCache, h) is None:
        session.add(LlmCache(text_hash=h, result_json=result, created_at=datetime.now(timezone.utc)))
        session.commit()
