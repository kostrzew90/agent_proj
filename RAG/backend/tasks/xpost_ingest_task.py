"""
RAG System — X Post Ingestion Task
Pipeline: X post URL → fetch content + GitHub READMEs → LLM analysis → chunk → embed → DB
"""

import asyncio
import logging

from tasks.celery_app import celery_app

logger = logging.getLogger("rag.tasks.xpost_ingest")

# Brief descriptions of existing projects for LLM context
PROJECT_CONTEXT = """Existing projects that tools could be integrated into:
1. RAG Pipeline — document processing, pgvector search, Ollama embeddings, FastAPI backend, React frontend
2. Selfmadeagent — self-hosted AI coding agent, Rust tool engine + Python orchestrator, LiteLLM, Langfuse monitoring
3. Trading App — Streamlit + GATE.io futures + APScheduler crypto trading
4. n8n — workflow automation platform (Docker Compose)
"""


@celery_app.task(name="tasks.xpost_ingest_task.ingest_xpost", bind=True)
def ingest_xpost(self, url: str, user_id: int, task_id: int):
    """Fetch X post, extract GitHub repos, analyze, chunk, embed, store."""
    logger.info("ingest_xpost: url=%s user_id=%s", url, user_id)
    try:
        asyncio.run(_ingest_pipeline(url, user_id, task_id))
    except Exception as exc:
        logger.exception("ingest_xpost failed: %s", exc)
        asyncio.run(_mark_failed(task_id, str(exc)))
        raise


async def _ingest_pipeline(url: str, user_id: int, task_id: int):
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
    from sqlalchemy import select
    from config import settings
    from core.database import Document, ProcessingTask, DocumentChunk
    from core.chunker import chunk_document
    from core.embeddings import EmbeddingClient
    from ingestion.xpost import process_xpost

    engine = create_async_engine(settings.database.async_url)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with Session() as db:
            await _set_progress(db, task_id, "running", 0.1)

            # --- Fetch X post + GitHub READMEs ---
            post = await process_xpost(url)
            logger.info("X post by %s: %d chars, %d repos found", post.author, len(post.text), len(post.repos))

            await _set_progress(db, task_id, "running", 0.3)

            # --- LLM analysis of repos ---
            analysis = ""
            if post.repos:
                analysis = _analyze_repos(post, settings)
                logger.info("LLM analysis: %d chars", len(analysis))

            await _set_progress(db, task_id, "running", 0.5)

            # --- Compose final document ---
            markdown = post.raw_content
            if analysis:
                markdown += f"\n\n---\n\n## Integration Analysis\n\n{analysis}\n"

            # --- Update document record ---
            result = await db.execute(
                select(Document).where(Document.source_url == url)
            )
            doc = result.scalar_one_or_none()
            if doc is None:
                raise ValueError("Document record not found")

            title = f"X: {post.author} — {post.text[:80]}..."
            doc.filename = title[:500]
            doc.file_size = len(markdown.encode())
            doc.file_hash = f"xpost_{hash(url) & 0xFFFFFFFF:08x}"
            doc.doc_metadata = {
                "author": post.author,
                "repos": [f"{r.owner}/{r.name}" for r in post.repos],
                "repo_count": len(post.repos),
                "has_analysis": bool(analysis),
            }
            await db.commit()

            await _set_progress(db, task_id, "running", 0.6)

            # --- Chunk ---
            chunks = chunk_document(markdown, file_type="markdown")
            logger.info("Chunked into %d chunks", len(chunks))

            # --- Embed ---
            embed_client = EmbeddingClient(
                base_url=settings.ai.ollama_url,
                model=settings.ai.embedding_model,
            )
            texts = [c.content for c in chunks]
            embeddings = embed_client.embed_batch(texts)

            await _set_progress(db, task_id, "running", 0.9)

            # --- Store chunks ---
            for chunk_data, embedding in zip(chunks, embeddings):
                db.add(DocumentChunk(
                    document_id=doc.id,
                    content=chunk_data.content,
                    chunk_index=chunk_data.chunk_index,
                    chunk_type=chunk_data.chunk_type,
                    section_title=chunk_data.section_title,
                    token_count=chunk_data.token_count,
                    chunk_metadata=chunk_data.metadata,
                    embedding=embedding,
                ))

            doc.status = "ready"
            doc.page_count = len(chunks)

            result = await db.execute(select(ProcessingTask).where(ProcessingTask.id == task_id))
            pt = result.scalar_one_or_none()
            if pt:
                pt.status = "completed"
                pt.progress = 1.0

            await db.commit()
            logger.info("ingest_xpost done: %s → %d chunks", url, len(chunks))

    finally:
        await engine.dispose()


def _analyze_repos(post, settings) -> str:
    """Use LLM to analyze how GitHub repos could integrate with existing projects."""
    repos_text = ""
    for repo in post.repos:
        repos_text += f"\n### {repo.owner}/{repo.name}\n"
        if repo.description:
            repos_text += f"{repo.description}\n"
        if repo.readme:
            # Only first 3000 chars of README for LLM context
            repos_text += f"\n{repo.readme[:3000]}\n"

    prompt = f"""Analyze these GitHub repositories found in an X post. For each repo, explain:
1. What it does (1-2 sentences)
2. Which of the existing projects it could improve and how
3. Specific integration idea (concrete, actionable)

{PROJECT_CONTEXT}

## X Post
{post.text}

## Repositories
{repos_text}

Be concise and practical. Focus on actionable integration ideas."""

    # Try OpenRouter first (faster), fallback to Ollama
    if settings.ai.openrouter_api_key:
        try:
            return _analyze_via_openrouter(prompt, settings)
        except Exception as e:
            logger.warning("OpenRouter analysis failed (%s), trying Ollama", e)

    return _analyze_via_ollama(prompt, settings)


def _analyze_via_openrouter(prompt: str, settings) -> str:
    """Sync OpenRouter call for analysis."""
    import httpx
    resp = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {settings.ai.openrouter_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.ai.openrouter_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2048,
            "temperature": 0.3,
        },
        timeout=60.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _analyze_via_ollama(prompt: str, settings) -> str:
    """Sync Ollama call for analysis."""
    from core.llm import LLMClient
    client = LLMClient()
    result = client.generate(prompt, max_tokens=2048)
    return result.text


async def _set_progress(db, task_id: int, status: str, progress: float):
    from sqlalchemy import select
    from core.database import ProcessingTask
    result = await db.execute(select(ProcessingTask).where(ProcessingTask.id == task_id))
    pt = result.scalar_one_or_none()
    if pt:
        pt.status = status
        pt.progress = progress
        await db.commit()


async def _mark_failed(task_id: int, error: str):
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
    from sqlalchemy import select
    from config import settings
    from core.database import ProcessingTask

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
