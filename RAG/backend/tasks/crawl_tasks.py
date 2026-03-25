"""
RAG System — Web Crawling Tasks (Celery)
Placeholder — full implementation in Phase 5.
"""

import logging

from tasks.celery_app import celery_app

logger = logging.getLogger("rag.tasks.crawl")


@celery_app.task(name="tasks.crawl_tasks.crawl_url", bind=True)
def crawl_url(self, url: str, depth: int = 1, user_id: int = None):
    """Crawl URL via Firecrawl and index results."""
    logger.info(f"Crawling {url} (depth={depth}, task={self.request.id})")
    # Phase 5: implement
    return {"url": url, "status": "not_implemented"}
