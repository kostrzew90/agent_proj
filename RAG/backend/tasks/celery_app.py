"""
RAG System — Celery Configuration
"""

from celery import Celery
from config import settings

celery_app = Celery(
    "rag",
    broker=settings.redis.url,
    backend=settings.redis.url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "tasks.document_tasks.*": {"queue": "documents"},
        "tasks.crawl_tasks.*": {"queue": "crawl"},
    },
    task_default_queue="default",
)

# Explicitly import task modules so Celery registers them
import tasks.document_tasks  # noqa: F401
import tasks.crawl_tasks  # noqa: F401
