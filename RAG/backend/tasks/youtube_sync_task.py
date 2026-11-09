"""
RAG System — YouTube Transcript Sync Task
Copies youtube_videos + youtube_embeddings from n8n DB → RAG DB.
Reuses existing embeddings — no re-embedding needed.
"""

import asyncio
import logging

from tasks.celery_app import celery_app

logger = logging.getLogger("rag.tasks.youtube_sync")

# n8n database connection (ai-postgres exposed on host port 5432)
N8N_DB_URL = "postgresql+asyncpg://n8n:n8npass@host.docker.internal:5432/n8n"


@celery_app.task(name="tasks.youtube_sync_task.sync_youtube_transcripts")
def sync_youtube_transcripts(user_id: int = 1):
    """
    Sync all YouTube transcripts from n8n DB to RAG DB.
    - Creates Document records (source_type='youtube') for each video
    - Copies DocumentChunk records with existing vector(768) embeddings
    - Creates a 'YouTube' tag and assigns all videos to it
    - Skips videos already present (idempotent)
    """
    logger.info("sync_youtube_transcripts started (user_id=%s)", user_id)
    try:
        result = asyncio.run(_sync_pipeline(user_id))
        logger.info("sync_youtube_transcripts done: %s", result)
        return result
    except Exception as exc:
        logger.exception("sync_youtube_transcripts failed: %s", exc)
        raise


async def _sync_pipeline(user_id: int) -> dict:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
    from sqlalchemy import text, select
    from config import settings
    from core.database import Document, DocumentChunk, Tag, DocumentTag

    # --- Connect to both DBs ---
    n8n_engine = create_async_engine(N8N_DB_URL, echo=False)
    rag_engine = create_async_engine(settings.database.async_url, echo=False)
    RagSession = async_sessionmaker(rag_engine, class_=AsyncSession, expire_on_commit=False)

    synced_videos = 0
    synced_chunks = 0
    skipped_videos = 0

    try:
        # --- Ensure 'YouTube' tag exists in RAG DB ---
        async with RagSession() as rag_db:
            result = await rag_db.execute(
                select(Tag).where(Tag.name == "YouTube", Tag.user_id == user_id)
            )
            youtube_tag = result.scalar_one_or_none()
            if not youtube_tag:
                youtube_tag = Tag(user_id=user_id, name="YouTube", color="#FF0000")
                rag_db.add(youtube_tag)
                await rag_db.commit()
                await rag_db.refresh(youtube_tag)
            tag_id = youtube_tag.id

        # --- Read all videos from n8n DB ---
        async with n8n_engine.connect() as n8n_conn:
            videos_result = await n8n_conn.execute(text("""
                SELECT video_id, title, webpage_url, channel_name,
                       upload_date, duration_seconds
                FROM youtube_videos
                ORDER BY created_at
            """))
            videos = videos_result.fetchall()

        logger.info("Found %d YouTube videos to sync", len(videos))

        for video in videos:
            video_id = video.video_id
            title = video.title or video_id
            url = video.webpage_url or f"https://www.youtube.com/watch?v={video_id}"

            async with RagSession() as rag_db:
                # Skip if already synced (check by source_url)
                existing = await rag_db.execute(
                    select(Document).where(Document.source_url == url)
                )
                if existing.scalar_one_or_none():
                    skipped_videos += 1
                    continue

                # Create Document record
                doc = Document(
                    user_id=user_id,
                    filename=title[:500],
                    file_type="transcript",
                    file_hash=f"yt_{video_id}",
                    status="ready",
                    source_type="youtube",
                    source_url=url,
                )
                rag_db.add(doc)
                await rag_db.flush()  # get doc.id

                # Assign YouTube tag
                rag_db.add(DocumentTag(document_id=doc.id, tag_id=tag_id))

                # Read chunks + embeddings from n8n DB
                async with n8n_engine.connect() as n8n_conn:
                    chunks_result = await n8n_conn.execute(text("""
                        SELECT chunk_index, chunk_text, start_time, end_time,
                               embedding::text AS embedding_str
                        FROM youtube_embeddings
                        WHERE video_id = :video_id
                        ORDER BY chunk_index
                    """), {"video_id": video_id})
                    chunks = chunks_result.fetchall()

                video_chunks = 0
                for chunk in chunks:
                    # Parse embedding from PostgreSQL vector string "[0.1,0.2,...]"
                    emb_str = chunk.embedding_str
                    embedding = [float(x) for x in emb_str.strip("[]").split(",")]

                    db_chunk = DocumentChunk(
                        document_id=doc.id,
                        content=chunk.chunk_text,
                        chunk_index=chunk.chunk_index,
                        chunk_type="transcript",
                        token_count=len(chunk.chunk_text.split()),
                        chunk_metadata={
                            "start_time": chunk.start_time,
                            "end_time": chunk.end_time,
                            "video_id": video_id,
                            "channel": video.channel_name,
                        },
                        embedding=embedding,
                    )
                    rag_db.add(db_chunk)
                    video_chunks += 1

                doc.page_count = video_chunks
                await rag_db.commit()

                synced_videos += 1
                synced_chunks += video_chunks
                logger.info(
                    "Synced video %s (%s) — %d chunks", video_id, title[:50], video_chunks
                )

    finally:
        await n8n_engine.dispose()
        await rag_engine.dispose()

    return {
        "synced_videos": synced_videos,
        "synced_chunks": synced_chunks,
        "skipped_videos": skipped_videos,
    }
