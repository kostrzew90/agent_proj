"""
RAG System — YouTube Ingestion Task
Pipeline: YouTube URL → transcript → chunk → embed → DB
"""

import asyncio
import logging
from pathlib import Path

from tasks.celery_app import celery_app

logger = logging.getLogger("rag.tasks.youtube_ingest")

UPLOAD_DIR = Path("/data/uploads")


@celery_app.task(name="tasks.youtube_ingest_task.ingest_youtube", bind=True)
def ingest_youtube(self, url: str, user_id: int, task_id: int, languages: list[str] | None = None):
    """Fetch YouTube transcript, chunk, embed and store in RAG DB."""
    logger.info("ingest_youtube: url=%s user_id=%s", url, user_id)
    try:
        asyncio.run(_ingest_pipeline(url, user_id, task_id, languages))
    except Exception as exc:
        logger.exception("ingest_youtube failed: %s", exc)
        asyncio.run(_mark_failed(task_id, str(exc)))
        raise


async def _ingest_pipeline(url: str, user_id: int, task_id: int, languages: list[str] | None):
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
    from sqlalchemy import select
    from config import settings
    from core.database import Document, ProcessingTask, DocumentChunk
    from core.chunker import chunk_document
    from core.embeddings import EmbeddingClient
    from ingestion.youtube import extract_video_id, fetch_video_metadata, fetch_transcript, download_audio, segments_to_markdown

    engine = create_async_engine(settings.database.async_url)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with Session() as db:
            await _set_progress(db, task_id, "running", 0.1)

            # --- Extract video ID ---
            video_id = extract_video_id(url)
            if not video_id:
                raise ValueError(f"Cannot extract video ID from: {url}")

            youtube_url = f"https://www.youtube.com/watch?v={video_id}"

            # --- Fetch metadata ---
            metadata = await fetch_video_metadata(video_id)
            title = metadata["title"]
            author = metadata["author"]
            logger.info("Video: %s — %s", video_id, title)

            await _set_progress(db, task_id, "running", 0.2)

            # --- Fetch transcript (VTT subtitles, fallback to Whisper) ---
            method = "subtitles"
            try:
                segments = fetch_transcript(video_id, languages)
                markdown = segments_to_markdown(segments, title)
                logger.info("Transcript via subtitles: %d segments, %d chars", len(segments), len(markdown))
            except Exception as sub_err:
                logger.warning("Subtitles unavailable (%s), falling back to Whisper transcription", sub_err)
                method = "whisper"
                import tempfile
                from ingestion.transcriber import transcribe as whisper_transcribe, segments_to_markdown as whisper_to_markdown
                with tempfile.TemporaryDirectory() as tmpdir:
                    audio_path = download_audio(video_id, tmpdir)
                    whisper_lang = languages[0] if languages else None
                    segments = whisper_transcribe(audio_path, language=whisper_lang)
                    markdown = whisper_to_markdown(segments, title)
                logger.info("Transcript via Whisper: %d segments, %d chars", len(segments), len(markdown))

            await _set_progress(db, task_id, "running", 0.4)

            # --- Save to disk ---
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            safe_name = video_id
            file_path = UPLOAD_DIR / f"yt_{safe_name}.md"
            file_path.write_text(markdown, encoding="utf-8")

            # --- Update document record ---
            result = await db.execute(
                select(Document).where(Document.source_url == youtube_url)
            )
            doc = result.scalar_one_or_none()
            if doc is None:
                raise ValueError("Document record not found")

            doc.filename = title[:500]
            doc.original_path = str(file_path)
            doc.file_size = len(markdown.encode())
            doc.file_hash = f"yt_{video_id}"
            doc.doc_metadata = {"author": author, "video_id": video_id, "segment_count": len(segments), "transcript_method": method}
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
            logger.info("ingest_youtube done: %s → %d chunks", video_id, len(chunks))

    finally:
        await engine.dispose()


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
