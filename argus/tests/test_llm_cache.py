from argus.llm.cache import text_hash, cache_get, cache_put

def test_hash_stable():
    assert text_hash("abc") == text_hash("abc")
    assert text_hash("abc") != text_hash("abd")

def test_miss_then_hit(session):
    h = text_hash("some headline")
    assert cache_get(session, h) is None
    cache_put(session, h, [{"asset": "BTC", "direction": "bull", "reasoning": "r"}])
    assert cache_get(session, h)[0]["asset"] == "BTC"

def test_empty_result_cached_as_list_not_none(session):
    h = text_hash("boring headline")
    cache_put(session, h, [])
    assert cache_get(session, h) == []
