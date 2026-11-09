import re
from pydantic import BaseModel, Field, field_validator, model_validator

# Pola, których tu nie trzymamy — treści idą do Langfuse (Etap 3), nie tutaj.
FORBIDDEN_FIELDS = {"prompt", "response", "input", "output", "messages", "context"}

_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}"
    r"|AIza[A-Za-z0-9_\-]{10,}"
    r"|Bearer\s+\S+"
    r"|(?:AKIA|ASIA)[A-Z0-9]{16}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|xox[bapr]-[A-Za-z0-9\-]{10,}"
    r"|(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{10,}"
    r")"
)
# scheme://user:password@host — redact the credentials, keep scheme/host visible.
_URL_CRED_RE = re.compile(r"://[^\s/@]+:[^\s/@]+@")


class CallIn(BaseModel):
    model_config = {"extra": "forbid"}

    project: str = Field(max_length=64)
    service: str = Field(max_length=64)
    environment: str = Field(max_length=32)
    host: str = Field(max_length=64)
    provider: str = Field(max_length=32)
    model: str = Field(max_length=200)
    call_type: str = Field(max_length=32)
    tokens_in: int = Field(default=0, ge=0)
    tokens_out: int = Field(default=0, ge=0)
    tokens_estimated: bool = False
    cost_usd: float | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    ok: bool
    error: str | None = None
    trace_id: str | None = Field(default=None, max_length=128)

    @field_validator("error")
    @classmethod
    def redact_and_truncate(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = _SECRET_RE.sub("[REDACTED]", v)
        v = _URL_CRED_RE.sub("://[REDACTED]@", v)
        return v[:300]

    @model_validator(mode="before")
    @classmethod
    def reject_content(cls, data):
        if isinstance(data, dict):
            found = FORBIDDEN_FIELDS & set(data)
            if found:
                raise ValueError(f"pola z trescia sa zabronione: {sorted(found)}")
        return data
