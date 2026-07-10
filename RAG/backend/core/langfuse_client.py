"""LangFuse client — singleton, no-op when keys not configured."""
import logging
from typing import Optional

logger = logging.getLogger("rag.core.langfuse")

_langfuse = None
_initialized = False


def get_langfuse():
    """Return Langfuse instance or None if not configured."""
    global _langfuse, _initialized
    if _initialized:
        return _langfuse
    _initialized = True

    from config import settings
    if not settings.langfuse.public_key or not settings.langfuse.secret_key:
        logger.info("LangFuse: keys not configured, tracing disabled")
        return None

    try:
        from langfuse import Langfuse
        _langfuse = Langfuse(
            public_key=settings.langfuse.public_key,
            secret_key=settings.langfuse.secret_key,
            host=settings.langfuse.host,
        )
        logger.info("LangFuse: connected to %s", settings.langfuse.host)
    except Exception as exc:
        logger.warning("LangFuse: init failed: %s", exc)
        _langfuse = None

    return _langfuse
