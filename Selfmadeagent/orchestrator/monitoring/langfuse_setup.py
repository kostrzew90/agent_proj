import os
from langfuse import Langfuse
from langfuse.decorators import langfuse_context

_langfuse_client: Langfuse | None = None


def init_langfuse() -> Langfuse | None:
    """Initialize Langfuse client from env vars. Returns None if not configured."""
    global _langfuse_client

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")
    host = os.getenv("LANGFUSE_HOST", "http://langfuse-server:3000")

    if not public_key or public_key == "pk-lf-change-me":
        return None

    _langfuse_client = Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        host=host,
    )
    return _langfuse_client


def get_langfuse() -> Langfuse | None:
    """Get the initialized Langfuse client."""
    return _langfuse_client


def flush_langfuse():
    """Flush pending Langfuse events."""
    if _langfuse_client:
        _langfuse_client.flush()
