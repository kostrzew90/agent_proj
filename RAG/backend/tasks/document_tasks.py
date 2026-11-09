"""
RAG System — Document Processing Tasks (Celery)
Full pipeline: parse (Docling) → chunk → embed (Ollama) → store in DB.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from tasks.celery_app import celery_app
from config import settings
from ingestion.parser import parse_document
from core.chunker import chunk_document
from core.embeddings import get_embedding_client

logger = logging.getLogger("rag.tasks.documents")

# Sync engine for Celery workers (async not needed in worker context)
_sync_engine = None


def get_sync_engine():
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_engine(settings.database.url, pool_size=5, max_overflow=10)
    return _sync_engine


def get_sync_session() -> Session:
    from sqlalchemy.orm import sessionmaker
    engine = get_sync_engine()
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


def _update_task_status(session: Session, task_id: int, status: str, progress: float = 0, error: str | None = None):
    """Update processing task status in DB."""
    from core.database import ProcessingTask
    values = {"status": status, "progress": progress}
    if status == "running":
        values["started_at"] = datetime.now(timezone.utc)
    if status in ("completed", "failed"):
        values["completed_at"] = datetime.now(timezone.utc)
    if error:
        values["error_message"] = error
    session.execute(
        update(ProcessingTask).where(ProcessingTask.id == task_id).values(**values)
    )
    session.commit()


def _update_document_status(session: Session, document_id: int, status: str, page_count: int | None = None, error: str | None = None):
    """Update document status in DB."""
    from core.database import Document
    values = {"status": status}
    if page_count is not None:
        values["page_count"] = page_count
    if status == "ready":
        values["processed_at"] = datetime.now(timezone.utc)
    if error:
        values["error_message"] = error
    session.execute(
        update(Document).where(Document.id == document_id).values(**values)
    )
    session.commit()


@celery_app.task(name="tasks.document_tasks.process_document", bind=True, max_retries=2)
def process_document(self, document_id: int, processing_task_id: int | None = None):
    """
    Full document processing pipeline:
    1. Parse document with Docling → markdown
    2. Chunk markdown → structured chunks
    3. Embed chunks via Ollama (qwen3-embedding:0.6b)
    4. Store chunks + embeddings in DB (pgvector)
    5. Update document status
    """
    from core.database import Document, DocumentChunk, ProcessingTask

    session = get_sync_session()
    try:
        # Get document record
        doc = session.execute(select(Document).where(Document.id == document_id)).scalar_one_or_none()
        if doc is None:
            logger.error(f"Document {document_id} not found")
            return {"document_id": document_id, "status": "error", "error": "Document not found"}

        # Update statuses
        _update_document_status(session, document_id, "processing")
        if processing_task_id:
            _update_task_status(session, processing_task_id, "running", progress=0.1)

        # Step 1: Parse document with Docling
        # Upload stores files as original_path (full path including hash prefix)
        file_path = Path(doc.original_path) if doc.original_path else None

        if file_path is None or not file_path.exists():
            # Fallback: try upload dir with hash_filename pattern
            file_path = Path(settings.app.upload_path) / f"{doc.file_hash}_{doc.filename}"

        if not file_path.exists():
            error = f"File not found: {file_path}"
            _update_document_status(session, document_id, "error", error=error)
            if processing_task_id:
                _update_task_status(session, processing_task_id, "failed", error=error)
            return {"document_id": document_id, "status": "error", "error": error}

        # Audio/video → transcribe with Whisper instead of Docling
        AUDIO_VIDEO_TYPES = {"audio", "mp3", "wav", "m4a", "ogg", "flac", "mp4", "mkv", "avi", "mov", "webm"}
        if doc.file_type in AUDIO_VIDEO_TYPES:
            logger.info(f"[{document_id}] Transcribing audio/video: {doc.filename}")
            if processing_task_id:
                _update_task_status(session, processing_task_id, "running", progress=0.2)

            from ingestion.transcriber import transcribe, segments_to_markdown
            segments = transcribe(str(file_path), language="pl")
            markdown = segments_to_markdown(segments, doc.filename)
            page_count = 1
        else:
            logger.info(f"[{document_id}] Parsing: {doc.filename}")
            parse_result = parse_document(file_path)

            if not parse_result.success:
                error = f"Parse failed: {parse_result.error}"
                _update_document_status(session, document_id, "error", error=error)
                if processing_task_id:
                    _update_task_status(session, processing_task_id, "failed", error=error)
                return {"document_id": document_id, "status": "error", "error": error}

            markdown = parse_result.markdown
            page_count = parse_result.page_count

        if processing_task_id:
            _update_task_status(session, processing_task_id, "running", progress=0.4)

        # Step 2: Chunk the parsed markdown
        logger.info(f"[{document_id}] Chunking: {len(markdown)} chars")
        chunks = chunk_document(markdown, file_type=doc.file_type)

        if processing_task_id:
            _update_task_status(session, processing_task_id, "running", progress=0.5)

        # Step 3: Embed chunks via Ollama
        logger.info(f"[{document_id}] Embedding {len(chunks)} chunks")
        embed_client = get_embedding_client()
        chunk_texts = [c.content for c in chunks]
        try:
            embeddings = embed_client.embed_batch(chunk_texts)
        except Exception as e:
            logger.error(f"[{document_id}] Embedding failed: {e}")
            # Store chunks without embeddings so we can retry embedding later
            embeddings = [None] * len(chunks)

        if processing_task_id:
            _update_task_status(session, processing_task_id, "running", progress=0.8)

        # Step 4: Delete old chunks (re-processing case) and store new ones
        session.execute(
            DocumentChunk.__table__.delete().where(DocumentChunk.document_id == document_id)
        )

        for chunk, embedding in zip(chunks, embeddings):
            db_chunk = DocumentChunk(
                document_id=document_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                embedding=embedding,
                page_number=chunk.page_number,
                section_title=chunk.section_title,
                chunk_type=chunk.chunk_type,
                token_count=chunk.token_count,
                chunk_metadata=chunk.metadata,
            )
            session.add(db_chunk)

        session.commit()

        # Step 5: Update document status — chunks with a failed embedding aren't
        # searchable, so don't report "ready" as if retrieval will work.
        embed_failed = any(e is None for e in embeddings)
        final_status = "error" if embed_failed else "ready"
        _update_document_status(
            session, document_id, final_status,
            page_count=page_count,
            error="Embedding failed — chunks stored but not searchable. Use /reprocess to retry." if embed_failed else None,
        )
        if processing_task_id:
            _update_task_status(
                session, processing_task_id,
                "failed" if embed_failed else "completed",
                progress=1.0,
            )

        result = {
            "document_id": document_id,
            "status": final_status,
            "chunks": len(chunks),
            "page_count": page_count,
            "total_tokens": sum(c.token_count for c in chunks),
        }
        logger.info(f"[{document_id}] Done: {result}")
        return result

    except Exception as e:
        logger.error(f"[{document_id}] Pipeline failed: {e}", exc_info=True)
        session.rollback()
        _update_document_status(session, document_id, "error", error=str(e))
        if processing_task_id:
            _update_task_status(session, processing_task_id, "failed", error=str(e))
        raise self.retry(exc=e, countdown=30)
    finally:
        session.close()
