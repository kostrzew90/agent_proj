import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from argus.db import Base
import argus.models as models
import argus.llm.router as router

SECRET = "sk-litellm-SECRET123"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    # Deterministic regardless of host/container env.
    monkeypatch.setenv("LITELLM_URL", "http://litellm.test:4000")
    monkeypatch.setenv("LITELLM_API_KEY", SECRET)
    monkeypatch.delenv("ARGUS_LLM_MODEL", raising=False)
    monkeypatch.delenv("ARGUS_LLM_TIMEOUT", raising=False)
    monkeypatch.setattr(router, "_last_alarm", 0.0)
    monkeypatch.setattr(router, "TG_TOKEN", "")


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    import argus.db
    monkeypatch.setattr(argus.db, "SessionLocal", Sess)
    return Sess


@pytest.fixture
def alarms(monkeypatch):
    sent = []
    monkeypatch.setattr(router.logger, "critical", lambda fmt, *a: sent.append(fmt % a))
    return sent


def _rows(Sess):
    with Sess() as s:
        return list(s.scalars(select(models.LlmCall)))


def _resp(status=200, json=None, headers=None, text=""):
    req = httpx.Request("POST", "http://litellm.test:4000/v1/chat/completions")
    if json is not None:
        return httpx.Response(status, json=json, headers=headers, request=req)
    return httpx.Response(status, text=text, headers=headers, request=req)


OK_BODY = {"model": "argus-extract", "choices": [{"message": {"content": "hello"}}],
           "usage": {"prompt_tokens": 11, "completion_tokens": 7}}


def test_success_records_ok_row_and_sends_request(db, monkeypatch):
    captured = {}

    def fake_post(url, **kw):
        captured.update(url=url, **kw)
        return _resp(json=OK_BODY, headers={"x-litellm-model-group": "argus-extract"})
    monkeypatch.setattr(router.httpx, "post", fake_post)
    assert router.call_llm("p", system="s", max_tokens=99) == "hello"
    assert captured["url"] == "http://litellm.test:4000/v1/chat/completions"
    assert captured["headers"]["Authorization"] == f"Bearer {SECRET}"
    assert captured["json"]["model"] == "argus-extract"
    assert captured["json"]["max_tokens"] == 99
    assert [m["role"] for m in captured["json"]["messages"]] == ["system", "user"]
    assert captured["timeout"] == 300.0
    (row,) = _rows(db)
    assert row.ok and row.provider == "litellm" and row.model == "argus-extract"
    assert (row.tokens_in, row.tokens_out) == (11, 7)


def test_no_system_message_when_empty(db, monkeypatch):
    seen = {}
    monkeypatch.setattr(router.httpx, "post", lambda url, **kw: seen.update(kw) or _resp(json=OK_BODY))
    router.call_llm("p")
    assert [m["role"] for m in seen["json"]["messages"]] == ["user"]


def test_fallback_records_actual_model(db, monkeypatch):
    headers = {"x-litellm-model-group": "argus-extract",
               "x-litellm-model-api-base": "https://openrouter.ai/api/v1",
               "x-litellm-attempted-fallbacks": "2"}
    monkeypatch.setattr(router.httpx, "post", lambda *a, **k: _resp(json=OK_BODY, headers=headers))
    assert router.call_llm("p") == "hello"
    (row,) = _rows(db)
    assert row.ok and row.model == "argus-extract@openrouter.ai"


@pytest.mark.parametrize("status", [429, 500])
def test_http_error_raises_records_and_alarms(db, alarms, monkeypatch, status):
    monkeypatch.setattr(router.httpx, "post", lambda *a, **k: _resp(status, text="boom"))
    with pytest.raises(RuntimeError, match=str(status)):
        router.call_llm("p")
    (row,) = _rows(db)
    assert not row.ok and str(status) in row.error
    assert len(alarms) == 1


def test_two_failures_alarm_once(db, alarms, monkeypatch):
    monkeypatch.setattr(router.httpx, "post", lambda *a, **k: _resp(500, text="boom"))
    for _ in range(2):
        with pytest.raises(RuntimeError):
            router.call_llm("p")
    assert len(_rows(db)) == 2
    assert len(alarms) == 1


@pytest.mark.parametrize("exc", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")])
def test_connection_errors_raise(db, alarms, monkeypatch, exc):
    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(router.httpx, "post", boom)
    with pytest.raises(RuntimeError):
        router.call_llm("p")
    (row,) = _rows(db)
    assert not row.ok


def test_missing_content_raises(db, monkeypatch):
    monkeypatch.setattr(router.httpx, "post",
                        lambda *a, **k: _resp(json={"choices": [{"message": {"content": None}}]}))
    with pytest.raises(RuntimeError):
        router.call_llm("p")
    assert not _rows(db)[0].ok


@pytest.mark.parametrize("var", ["LITELLM_URL", "LITELLM_API_KEY"])
def test_missing_config_no_http_request(db, monkeypatch, var):
    monkeypatch.delenv(var)

    def fail(*a, **k):
        raise AssertionError("HTTP request must not be sent")
    monkeypatch.setattr(router.httpx, "post", fail)
    with pytest.raises(RuntimeError, match="LITELLM"):
        router.call_llm("p")
    assert not _rows(db)[0].ok


def test_api_key_never_leaks(db, alarms, monkeypatch):
    monkeypatch.setattr(router.httpx, "post",
                        lambda *a, **k: _resp(401, text=f"bad key {SECRET} given"))
    with pytest.raises(RuntimeError) as ei:
        router.call_llm("p")
    assert SECRET not in str(ei.value)
    assert SECRET not in _rows(db)[0].error
    assert alarms and all(SECRET not in a for a in alarms)
