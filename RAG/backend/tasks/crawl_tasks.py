"""
RAG System — Web Crawling Tasks (Celery)
Pipeline: URL → mdream → markdown → chunk → embed → DB
"""

import asyncio
import hashlib
import logging
from pathlib import Path

from tasks.celery_app import celery_app

logger = logging.getLogger("rag.tasks.crawl")

UPLOAD_DIR = Path("/data/uploads")


@celery_app.task(name="tasks.crawl_tasks.crawl_url")
def crawl_url(url: str, depth: int = 1, user_id: int = None, task_id: int = None):
    """
    Crawl a URL via mdream, chunk + embed the markdown, store in DB.
    Uses the same embed+store pipeline as document_tasks.
    """
    logger.info("crawl_url started: url=%s depth=%d user_id=%s", url, depth, user_id)

    try:
        asyncio.run(_crawl_pipeline(url, depth, user_id, task_id))
    except Exception as exc:
        logger.exception("crawl_url failed: %s", exc)
        if task_id:
            asyncio.run(_mark_task_failed(task_id, str(exc)))
        raise


async def _crawl_pipeline(url: str, depth: int, user_id: int | None, task_id: int | None):
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
    from config import settings
    from core.database import Document, ProcessingTask
    from ingestion.crawler import WebCrawler
    from core.embeddings import EmbeddingClient
    from sqlalchemy import select

    engine = create_async_engine(settings.database.async_url)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with Session() as db:
            # --- Update task status ---
            if task_id:
                result = await db.execute(select(ProcessingTask).where(ProcessingTask.id == task_id))
                pt = result.scalar_one_or_none()
                if pt:
                    pt.status = "running"
                    pt.progress = 0.1
                    await db.commit()

            # --- Fetch + extract markdown ---
            crawler = WebCrawler()
            crawl_result = await crawler.fetch_markdown(url)
            markdown = crawl_result["markdown"]
            title = crawl_result["title"]
            content_hash = crawl_result["content_hash"]

            # --- Save markdown to disk ---
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            safe_name = url.replace("://", "_").replace("/", "_")[:80]
            file_path = UPLOAD_DIR / f"{content_hash[:8]}_{safe_name}.md"
            file_path.write_text(markdown, encoding="utf-8")

            # --- Update document record ---
            result = await db.execute(
                select(Document).where(Document.source_url == url)
            )
            doc = result.scalar_one_or_none()
            if doc is None:
                raise ValueError("Document record not found — should be created by the API endpoint")

            doc.original_path = str(file_path)
            doc.file_size = len(markdown.encode())
            await db.commit()

            if task_id:
                result = await db.execute(select(ProcessingTask).where(ProcessingTask.id == task_id))
                pt = result.scalar_one_or_none()
                if pt:
                    pt.progress = 0.4
                    await db.commit()

            # --- Chunk markdown ---
            from core.chunker import chunk_document
            chunks = chunk_document(markdown, file_type="markdown")

            if task_id:
                result = await db.execute(select(ProcessingTask).where(ProcessingTask.id == task_id))
                pt = result.scalar_one_or_none()
                if pt:
                    pt.progress = 0.6
                    await db.commit()

            # --- Embed chunks ---
            texts = [c.content for c in chunks]
            embeddings = EmbeddingClient().embed_batch(texts)

            # --- Store chunks + embeddings in DB ---
            from core.database import DocumentChunk

            for chunk_data, embedding in zip(chunks, embeddings):
                chunk = DocumentChunk(
                    document_id=doc.id,
                    content=chunk_data.content,
                    chunk_index=chunk_data.chunk_index,
                    chunk_type=chunk_data.chunk_type,
                    section_title=chunk_data.section_title,
                    token_count=chunk_data.token_count,
                    chunk_metadata=chunk_data.metadata,
                    embedding=embedding,
                )
                db.add(chunk)

            doc.status = "ready"
            doc.page_count = 1

            if task_id:
                result = await db.execute(select(ProcessingTask).where(ProcessingTask.id == task_id))
                pt = result.scalar_one_or_none()
                if pt:
                    pt.status = "completed"
                    pt.progress = 1.0
                    await db.commit()

            await db.commit()
            logger.info(
                "crawl_url complete: url=%s doc_id=%d chunks=%d",
                url, doc.id, len(chunks),
            )

    finally:
        await engine.dispose()


async def _mark_task_failed(task_id: int, error: str):
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
    from config import settings
    from core.database import ProcessingTask
    from sqlalchemy import select

    engine = create_async_engine(settings.database.async_url)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with Session() as db:
            result = await db.execute(select(ProcessingTask).where(ProcessingTask.id == task_id))
            pt = result.scalar_one_or_none()
            if pt:
                pt.status = "failed"
                pt.error_message = error[:500]
                await db.commit()
    finally:
        await engine.dispose()
