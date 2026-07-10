"""
RAG System — Rate Limiting
Uses slowapi with Redis backend to protect AI inference endpoints.
"""

import logging
from slowapi import Limiter
from slowapi.util import get_remote_address
from config import settings

logger = logging.getLogger(__name__)

# Use Redis as storage backend for distributed rate limiting
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.redis.url,
    default_limits=["60/minute"],
)
