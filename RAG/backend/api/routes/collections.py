"""
RAG System — Collection Routes
Folders (hierarchical) and Tags (flat) CRUD.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.database import (
    Folder, Tag, DocumentFolder, DocumentTag, User, get_db,
)
from api.deps import get_current_user

router = APIRouter()


# === Schemas ===

class FolderCreate(BaseModel):
    name: str
    parent_id: int | None = None


class FolderUpdate(BaseModel):
    name: str | None = None
    parent_id: int | None = None


class FolderResponse(BaseModel):
    id: int
    name: str
    parent_id: int | None
    created_at: datetime
    children: list["FolderResponse"] = []

    model_config = {"from_attributes": True}


class TagCreate(BaseModel):
    name: str
    color: str = "#3B82F6"


class TagResponse(BaseModel):
    id: int
    name: str
    color: str
    created_at: datetime
    document_count: int = 0

    model_config = {"from_attributes": True}


class AssignRequest(BaseModel):
    ids: list[int]


# === Folder Endpoints ===

@router.post("/folders", response_model=FolderResponse, status_code=201)
async def create_folder(
    body: FolderCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.parent_id:
        parent = await db.execute(
            select(Folder).where(Folder.id == body.parent_id, Folder.user_id == user.id)
        )
        if not parent.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Parent folder not found")

    folder = Folder(name=body.name, parent_id=body.parent_id, user_id=user.id)
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return folder


@router.get("/folders", response_model=list[FolderResponse])
async def list_folders(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Folder)
        .where(Folder.user_id == user.id, Folder.parent_id.is_(None))
        .options(selectinload(Folder.children))
        .order_by(Folder.name)
    )
    return result.scalars().all()


@router.put("/folders/{folder_id}", response_model=FolderResponse)
async def update_folder(
    folder_id: int,
    body: FolderUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Folder).where(Folder.id == folder_id, Folder.user_id == user.id)
    )
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    if body.name is not None:
        folder.name = body.name
    if body.parent_id is not None:
        if body.parent_id == folder.id:
            raise HTTPException(status_code=400, detail="Folder cannot be its own parent")
        folder.parent_id = body.parent_id

    await db.commit()
    await db.refresh(folder)
    return folder


@router.delete("/folders/{folder_id}", status_code=204)
async def delete_folder(
    folder_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Folder).where(Folder.id == folder_id, Folder.user_id == user.id)
    )
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    await db.delete(folder)
    await db.commit()


# === Tag Endpoints ===

@router.post("/tags", response_model=TagResponse, status_code=201)
async def create_tag(
    body: TagCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(Tag).where(Tag.name == body.name, Tag.user_id == user.id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Tag already exists")

    tag = Tag(name=body.name, color=body.color, user_id=user.id)
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return TagResponse(id=tag.id, name=tag.name, color=tag.color, created_at=tag.created_at)


@router.get("/tags", response_model=list[TagResponse])
async def list_tags(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Tag).where(Tag.user_id == user.id).order_by(Tag.name)
    )
    tags = result.scalars().all()
    responses = []
    for tag in tags:
        count_result = await db.execute(
            select(DocumentTag.document_id).where(DocumentTag.tag_id == tag.id)
        )
        count = len(count_result.all())
        responses.append(
            TagResponse(id=tag.id, name=tag.name, color=tag.color,
                        created_at=tag.created_at, document_count=count)
        )
    return responses


@router.delete("/tags/{tag_id}", status_code=204)
async def delete_tag(
    tag_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Tag).where(Tag.id == tag_id, Tag.user_id == user.id)
    )
    tag = result.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    await db.delete(tag)
    await db.commit()


# === Document <-> Folder/Tag assignment ===

@router.post("/documents/{document_id}/folders", status_code=204)
async def assign_document_to_folders(
    document_id: int,
    body: AssignRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from core.database import Document
    doc = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == user.id)
    )
    if not doc.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Document not found")

    for fid in body.ids:
        folder = await db.execute(
            select(Folder).where(Folder.id == fid, Folder.user_id == user.id)
        )
        if folder.scalar_one_or_none():
            existing = await db.execute(
                select(DocumentFolder).where(
                    DocumentFolder.document_id == document_id,
                    DocumentFolder.folder_id == fid,
                )
            )
            if not existing.scalar_one_or_none():
                db.add(DocumentFolder(document_id=document_id, folder_id=fid))
    await db.commit()


@router.post("/documents/{document_id}/tags", status_code=204)
async def assign_document_tags(
    document_id: int,
    body: AssignRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from core.database import Document
    doc = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == user.id)
    )
    if not doc.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Document not found")

    for tid in body.ids:
        tag = await db.execute(
            select(Tag).where(Tag.id == tid, Tag.user_id == user.id)
        )
        if tag.scalar_one_or_none():
            existing = await db.execute(
                select(DocumentTag).where(
                    DocumentTag.document_id == document_id,
                    DocumentTag.tag_id == tid,
                )
            )
            if not existing.scalar_one_or_none():
                db.add(DocumentTag(document_id=document_id, tag_id=tid))
    await db.commit()
