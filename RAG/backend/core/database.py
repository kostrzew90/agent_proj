"""
RAG System — Database Models & Session Management
Uses async SQLAlchemy with pgvector support.
"""

from datetime import datetime, timezone
from typing import AsyncGenerator

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey,
    Integer, String, Text, BigInteger, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship

from config import settings

engine = create_async_engine(
    settings.database.async_url,
    echo=settings.app.debug,
    pool_size=10,
    max_overflow=20,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def utcnow():
    return datetime.now(timezone.utc)


# =============================================================
# Models
# =============================================================

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    display_name = Column(String(200))
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    profile = relationship("UserProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="user")
    chat_sessions = relationship("ChatSession", back_populates="user", cascade="all, delete-orphan")
    folders = relationship("Folder", back_populates="user", cascade="all, delete-orphan")
    tags = relationship("Tag", back_populates="user", cascade="all, delete-orphan")


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    frequent_topics = Column(JSONB, default=dict)
    preferred_language = Column(String(10), default="auto")
    settings = Column(JSONB, default=dict)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="profile")


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    filename = Column(String(500), nullable=False)
    original_path = Column(Text)
    file_type = Column(String(50), nullable=False)
    file_hash = Column(String(64), nullable=False)
    file_size = Column(BigInteger)
    page_count = Column(Integer)
    status = Column(String(20), default="pending")
    source_type = Column(String(20), default="upload")
    source_url = Column(Text)
    doc_metadata = Column("metadata", JSONB, default=dict)
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    processed_at = Column(DateTime(timezone=True))

    user = relationship("User", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
    processing_tasks = relationship("ProcessingTask", back_populates="document", cascade="all, delete-orphan")
    folders = relationship("Folder", secondary="document_folders", back_populates="documents")
    tags = relationship("Tag", secondary="document_tags", back_populates="documents")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"))
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(settings.ai.embedding_dimension))
    page_number = Column(Integer)
    section_title = Column(String(500))
    chunk_type = Column(String(50), default="text")
    token_count = Column(Integer)
    chunk_metadata = Column("metadata", JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    document = relationship("Document", back_populates="chunks")


class Folder(Base):
    __tablename__ = "folders"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    parent_id = Column(Integer, ForeignKey("folders.id", ondelete="CASCADE"))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    created_at = Column(DateTime(timezone=True), default=utcnow)

    user = relationship("User", back_populates="folders")
    children = relationship("Folder", back_populates="parent", cascade="all, delete-orphan")
    parent = relationship("Folder", back_populates="children", remote_side=[id])
    documents = relationship("Document", secondary="document_folders", back_populates="folders")


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("name", "user_id"),)

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    color = Column(String(7), default="#3B82F6")
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    created_at = Column(DateTime(timezone=True), default=utcnow)

    user = relationship("User", back_populates="tags")
    documents = relationship("Document", secondary="document_tags", back_populates="tags")


class DocumentFolder(Base):
    __tablename__ = "document_folders"

    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    folder_id = Column(Integer, ForeignKey("folders.id", ondelete="CASCADE"), primary_key=True)


class DocumentTag(Base):
    __tablename__ = "document_tags"

    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    title = Column(String(300))
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="chat_sessions")
    messages = relationship("ChatMessage", back_populates="chat_session", cascade="all, delete-orphan")
    contexts = relationship("ChatContext", back_populates="chat_session", cascade="all, delete-orphan")


class ChatContext(Base):
    __tablename__ = "chat_context"

    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"))
    folder_id = Column(Integer, ForeignKey("folders.id", ondelete="SET NULL"))
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="SET NULL"))

    chat_session = relationship("ChatSession", back_populates="contexts")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"))
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    sources = Column(JSONB)
    groundedness_score = Column(Float)
    completeness_score = Column(Float)
    relevance_score = Column(Float)
    token_count = Column(Integer)
    latency_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    chat_session = relationship("ChatSession", back_populates="messages")


class ProcessingTask(Base):
    __tablename__ = "processing_tasks"

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"))
    celery_task_id = Column(String(255))
    task_type = Column(String(50), nullable=False)
    status = Column(String(20), default="pending")
    progress = Column(Float, default=0)
    error_message = Column(Text)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utcnow)

    document = relationship("Document", back_populates="processing_tasks")


class EmbeddingBenchmark(Base):
    __tablename__ = "embedding_benchmarks"

    id = Column(Integer, primary_key=True)
    model_name = Column(String(200), nullable=False)
    model_dimension = Column(Integer)
    recall_at_5 = Column(Float)
    recall_at_10 = Column(Float)
    mrr = Column(Float)
    ndcg_at_10 = Column(Float)
    avg_latency_ms = Column(Float)
    test_set_size = Column(Integer)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow)


# =============================================================
# Session dependency
# =============================================================

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
