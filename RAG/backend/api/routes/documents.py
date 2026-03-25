"""
RAG System — Document Routes
Upload, list, get, delete documents. Processing triggered via Celery.
"""

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from core.database import (
    Document, DocumentChunk, ProcessingTask, Folder, Tag,
    DocumentFolder, DocumentTag, get_db,
)
from api.deps import get_current_user
from core.database import User

router = APIRouter()

UPLOAD_DIR = Path("/data/uploads")


# === Schemas ===

class DocumentResponse(BaseModel):
    id: int
    filename: str
    file_type: str
    file_size: int | None
    page_count: int | None
    status: str
    source_type: str
    source_url: str | None
    created_at: datetime
    processed_at: datetime | None
    folder_ids: list[int] = []
    tag_ids: list[int] = []

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int


class TaskStatusResponse(BaseModel):
    task_id: int
    document_id: int
    task_type: str
    status: str
    progress: float
    error_message: str | None


class DuplicateCheckResponse(BaseModel):
    is_duplicate: bool
    existing_document_id: int | None = None
    existing_filename: str | None = None
    existing_created_at: datetime | None = None


# === Helpers ===

async def compute_file_hash(file: UploadFile) -> str:
    sha256 = hashlib.sha256()
    while chunk := await file.read(8192):
        sha256.update(chunk)
    await file.seek(0)
    return sha256.hexdigest()


def get_file_type(filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    type_map = {
        "pdf": "pdf", "docx": "docx", "doc": "doc", "txt": "txt",
        "md": "markdown", "csv": "csv", "rtf": "rtf",
        "pptx": "pptx", "xlsx": "xlsx",
        "png": "image", "jpg": "image", "jpeg": "image", "tiff": "image", "bmp": "image",
        "mp3": "audio", "wav": "audio", "m4a": "audio", "ogg": "audio", "flac": "audio",
    }
    return type_map.get(ext, "unknown")


# === Endpoints ===

@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    folder_id: int | None = Query(None),
    tag_ids: str | None = Query(None, description="Comma-separated tag IDs"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Validate file size
    content = await file.read()
    if len(content) > settings.app.max_file_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {settings.app.max_file_size_mb}MB limit",
        )
    await file.seek(0)

    file_type = get_file_type(file.filename)
    if file_type == "unknown":
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.filename}")

    file_hash = await compute_file_hash(file)

    # Check for duplicates
    existing = await db.execute(
        select(Document).where(Document.file_hash == file_hash, Document.user_id == user.id)
    )
    existing_doc = existing.scalar_one_or_none()
    if existing_doc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Duplicate document detected",
                "existing_document_id": existing_doc.id,
                "existing_filename": existing_doc.filename,
                "existing_created_at": existing_doc.created_at.isoformat(),
            },
        )

    # Save file to disk
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_path = UPLOAD_DIR / f"{file_hash}_{file.filename}"
    async with aiofiles.open(file_path, "wb") as f:
        await file.seek(0)
        await f.write(content)

    # Create document record
    doc = Document(
        user_id=user.id,
        filename=file.filename,
        original_path=str(file_path),
        file_type=file_type,
        file_hash=file_hash,
        file_size=len(content),
        status="pending",
        source_type="upload",
    )
    db.add(doc)
    await db.flush()

    # Assign folder
    if folder_id:
        folder = await db.execute(
            select(Folder).where(Folder.id == folder_id, Folder.user_id == user.id)
        )
        if not folder.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Folder not found")
        db.add(DocumentFolder(document_id=doc.id, folder_id=folder_id))

    # Assign tags
    parsed_tag_ids = []
    if tag_ids:
        parsed_tag_ids = [int(t.strip()) for t in tag_ids.split(",") if t.strip()]
        for tid in parsed_tag_ids:
            tag = await db.execute(select(Tag).where(Tag.id == tid, Tag.user_id == user.id))
            if tag.scalar_one_or_none():
                db.add(DocumentTag(document_id=doc.id, tag_id=tid))

    # Create processing task
    task = ProcessingTask(
        document_id=doc.id,
        task_type="full_pipeline",
        status="pending",
    )
    db.add(task)

    await db.commit()
    await db.refresh(doc)

    # Dispatch Celery processing task
    from tasks.document_tasks import process_document
    celery_result = process_document.delay(doc.id, task.id)

    # Store Celery task ID
    task.celery_task_id = celery_result.id
    await db.commit()

    return DocumentResponse(
        id=doc.id,
        filename=doc.filename,
        file_type=doc.file_type,
        file_size=doc.file_size,
        page_count=doc.page_count,
        status=doc.status,
        source_type=doc.source_type,
        source_url=doc.source_url,
        created_at=doc.created_at,
        processed_at=doc.processed_at,
        folder_ids=[folder_id] if folder_id else [],
        tag_ids=parsed_tag_ids,
    )


@router.post("/upload/force", response_model=DocumentResponse, status_code=201)
async def upload_document_force(
    file: UploadFile = File(...),
    replace_document_id: int | None = Query(None, description="ID of document to replace"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload even if duplicate exists. Optionally replace an existing document."""
    if replace_document_id:
        old_doc = await db.execute(
            select(Document).where(Document.id == replace_document_id, Document.user_id == user.id)
        )
        old = old_doc.scalar_one_or_none()
        if old:
            await db.delete(old)
            await db.flush()

    content = await file.read()
    await file.seek(0)
    file_hash = await compute_file_hash(file)
    file_type = get_file_type(file.filename)

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_path = UPLOAD_DIR / f"{file_hash}_{file.filename}"
    async with aiofiles.open(file_path, "wb") as f:
        await file.seek(0)
        await f.write(content)

    doc = Document(
        user_id=user.id,
        filename=file.filename,
        original_path=str(file_path),
        file_type=file_type,
        file_hash=file_hash,
        file_size=len(content),
        status="pending",
        source_type="upload",
    )
    db.add(doc)
    await db.flush()

    task = ProcessingTask(document_id=doc.id, task_type="full_pipeline", status="pending")
    db.add(task)
    await db.commit()
    await db.refresh(doc)

    return DocumentResponse(
        id=doc.id, filename=doc.filename, file_type=doc.file_type,
        file_size=doc.file_size, page_count=doc.page_count, status=doc.status,
        source_type=doc.source_type, source_url=doc.source_url,
        created_at=doc.created_at, processed_at=doc.processed_at,
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    folder_id: int | None = Query(None),
    tag_id: int | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    file_type: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Document).where(Document.user_id == user.id)

    if status_filter:
        query = query.where(Document.status == status_filter)
    if file_type:
        query = query.where(Document.file_type == file_type)
    if folder_id:
        query = query.join(DocumentFolder).where(DocumentFolder.folder_id == folder_id)
    if tag_id:
        query = query.join(DocumentTag).where(DocumentTag.tag_id == tag_id)

    # Count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar_one()

    # Fetch
    query = query.order_by(Document.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    docs = result.scalars().all()

    return DocumentListResponse(
        documents=[
            DocumentResponse(
                id=d.id, filename=d.filename, file_type=d.file_type,
                file_size=d.file_size, page_count=d.page_count, status=d.status,
                source_type=d.source_type, source_url=d.source_url,
                created_at=d.created_at, processed_at=d.processed_at,
            )
            for d in docs
        ],
        total=total,
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == user.id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentResponse(
        id=doc.id, filename=doc.filename, file_type=doc.file_type,
        file_size=doc.file_size, page_count=doc.page_count, status=doc.status,
        source_type=doc.source_type, source_url=doc.source_url,
        created_at=doc.created_at, processed_at=doc.processed_at,
    )


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == user.id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Delete file from disk
    if doc.original_path and os.path.exists(doc.original_path):
        os.remove(doc.original_path)

    await db.delete(doc)  # cascades to chunks, tasks, folder/tag relations
    await db.commit()


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ProcessingTask)
        .join(Document)
        .where(ProcessingTask.id == task_id, Document.user_id == user.id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskStatusResponse(
        task_id=task.id,
        document_id=task.document_id,
        task_type=task.task_type,
        status=task.status,
        progress=task.progress,
        error_message=task.error_message,
    )
