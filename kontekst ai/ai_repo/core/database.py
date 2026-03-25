"""SQLAlchemy models + database operations for ai_repo."""

from __future__ import annotations

import logging
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker

from ai_repo.config import settings

logger = logging.getLogger(__name__)

Base = declarative_base()


# ── ORM Models ──────────────────────────────────────────────────────────────

class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    path = Column(Text, nullable=False)
    type = Column(Text, nullable=False, default="python")
    hash = Column(Text, nullable=False)
    mtime = Column(Float, nullable=False)
    repo_id = Column(Text, nullable=False, default="default")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"))
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    start_line = Column(Integer)
    end_line = Column(Integer)
    tokens = Column(Integer)
    embedding = Column(Vector(768))

    document = relationship("Document", back_populates="chunks")


class Symbol(Base):
    __tablename__ = "symbols"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    kind = Column(Text, nullable=False)
    file_path = Column(Text, nullable=False)
    start_line = Column(Integer)
    end_line = Column(Integer)
    signature = Column(Text)
    docstring = Column(Text)
    repo_id = Column(Text, nullable=False, default="default")


class Edge(Base):
    __tablename__ = "edges"

    id = Column(Integer, primary_key=True)
    src_kind = Column(Text, nullable=False)
    src_id = Column(Integer, nullable=False)
    dst_kind = Column(Text, nullable=False)
    dst_id = Column(Integer, nullable=False)
    edge_type = Column(Text, nullable=False)
    weight = Column(Float, default=1.0)


class ProjectMemory(Base):
    __tablename__ = "project_memory"

    id = Column(Integer, primary_key=True)
    key = Column(Text, nullable=False, unique=True)
    value = Column(Text, nullable=False)
    confidence = Column(Float, default=0.8)
    tags = Column(ARRAY(Text), default=[])
    source = Column(Text)
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class RetrievalLog(Base):
    __tablename__ = "retrieval_logs"

    id = Column(Integer, primary_key=True)
    query = Column(Text, nullable=False)
    topk = Column(Integer, default=10)
    latency_ms = Column(Float)
    provider_used = Column(Text, default="ollama")
    context_tokens = Column(Integer)
    semantic_count = Column(Integer)
    keyword_count = Column(Integer)
    final_count = Column(Integer)
    embedding_ms = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class LogEvent(Base):
    __tablename__ = "log_events"

    id = Column(Integer, primary_key=True)
    ts = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    service = Column(Text)
    level = Column(Text)
    error_signature = Column(Text)
    trace_id = Column(Text)
    message = Column(Text)
    meta_json = Column(JSONB, default={})


class IndexingJob(Base):
    __tablename__ = "indexing_jobs"

    id = Column(Integer, primary_key=True)
    repo_id = Column(Text, nullable=False, default="default")
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(DateTime(timezone=True))
    files_scanned = Column(Integer, default=0)
    files_indexed = Column(Integer, default=0)
    files_skipped = Column(Integer, default=0)
    files_errored = Column(Integer, default=0)
    chunks_created = Column(Integer, default=0)
    symbols_found = Column(Integer, default=0)
    duration_ms = Column(Float)
    status = Column(Text, nullable=False, default="running")


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id = Column(Integer, primary_key=True)
    ts = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    provider = Column(Text, nullable=False)
    model = Column(Text, nullable=False)
    purpose = Column(Text)
    input_tokens = Column(Integer)
    output_tokens = Column(Integer)
    latency_ms = Column(Float)
    success = Column(Boolean, nullable=False, default=True)
    error_message = Column(Text)


# ── Database Manager ────────────────────────────────────────────────────────

class Database:
    """Synchronous database operations for ai_repo."""

    def __init__(self, url: Optional[str] = None):
        self.url = url or settings.database.url
        self.engine = create_engine(self.url, pool_pre_ping=True)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def get_session(self) -> Session:
        return self.SessionLocal()

    # ── Documents ───────────────────────────────────────────────────────

    def upsert_document(self, path: str, file_type: str, file_hash: str,
                        mtime: float, repo_id: str = "default") -> Document:
        with self.get_session() as session:
            doc = session.query(Document).filter_by(path=path, repo_id=repo_id).first()
            if doc:
                doc.hash = file_hash
                doc.mtime = mtime
                doc.type = file_type
                # Delete old chunks on re-index
                session.query(Chunk).filter_by(document_id=doc.id).delete()
            else:
                doc = Document(
                    path=path, type=file_type, hash=file_hash,
                    mtime=mtime, repo_id=repo_id,
                )
                session.add(doc)
            session.commit()
            session.refresh(doc)
            return doc

    def get_document(self, path: str, repo_id: str = "default") -> Optional[Document]:
        with self.get_session() as session:
            return session.query(Document).filter_by(path=path, repo_id=repo_id).first()

    def delete_document(self, path: str, repo_id: str = "default"):
        with self.get_session() as session:
            session.query(Document).filter_by(path=path, repo_id=repo_id).delete()
            session.commit()

    def get_all_documents(self, repo_id: str = "default") -> list[Document]:
        with self.get_session() as session:
            return session.query(Document).filter_by(repo_id=repo_id).all()

    # ── Chunks ──────────────────────────────────────────────────────────

    def insert_chunks(self, document_id: int, chunks: list[dict]):
        """Insert multiple chunks for a document.

        Each dict: {chunk_index, content, start_line, end_line, tokens}
        """
        with self.get_session() as session:
            for c in chunks:
                chunk = Chunk(
                    document_id=document_id,
                    chunk_index=c["chunk_index"],
                    content=c["content"],
                    start_line=c.get("start_line"),
                    end_line=c.get("end_line"),
                    tokens=c.get("tokens"),
                )
                session.add(chunk)
            session.commit()

    def update_chunk_embedding(self, chunk_id: int, embedding: list[float]):
        with self.get_session() as session:
            chunk = session.query(Chunk).get(chunk_id)
            if chunk:
                chunk.embedding = embedding
                session.commit()

    def bulk_update_embeddings(self, updates: list[tuple[int, list[float]]]):
        """Update embeddings for multiple chunks: [(chunk_id, embedding), ...]"""
        with self.get_session() as session:
            for chunk_id, embedding in updates:
                session.query(Chunk).filter_by(id=chunk_id).update(
                    {"embedding": embedding}
                )
            session.commit()

    def get_chunks_without_embeddings(self, limit: int = 100) -> list[Chunk]:
        with self.get_session() as session:
            return (
                session.query(Chunk)
                .filter(Chunk.embedding.is_(None))
                .limit(limit)
                .all()
            )

    # ── Semantic search ─────────────────────────────────────────────────

    def semantic_search(self, embedding: list[float], top_n: int = 50,
                        repo_id: Optional[str] = None) -> list[dict]:
        """Cosine similarity search on chunk embeddings."""
        with self.get_session() as session:
            query = text("""
                SELECT c.id, c.content, c.start_line, c.end_line,
                       d.path, d.type,
                       1 - (c.embedding <=> CAST(:embedding as vector)) AS score
                FROM chunks c
                JOIN documents d ON c.document_id = d.id
                WHERE c.embedding IS NOT NULL
                  AND (:repo_id IS NULL OR d.repo_id = :repo_id)
                ORDER BY c.embedding <=> CAST(:embedding as vector)
                LIMIT :top_n
            """)
            rows = session.execute(query, {
                "embedding": str(embedding),
                "repo_id": repo_id,
                "top_n": top_n,
            }).fetchall()
            return [
                {"chunk_id": r[0], "content": r[1], "start_line": r[2],
                 "end_line": r[3], "path": r[4], "type": r[5], "score": float(r[6])}
                for r in rows
            ]

    def keyword_search(self, query_text: str, top_n: int = 50,
                       repo_id: Optional[str] = None) -> list[dict]:
        """Full-text search using PostgreSQL tsvector."""
        with self.get_session() as session:
            query = text("""
                SELECT c.id, c.content, c.start_line, c.end_line,
                       d.path, d.type,
                       ts_rank(to_tsvector('simple', c.content),
                               plainto_tsquery('simple', :query)) AS score
                FROM chunks c
                JOIN documents d ON c.document_id = d.id
                WHERE to_tsvector('simple', c.content) @@ plainto_tsquery('simple', :query)
                  AND (:repo_id IS NULL OR d.repo_id = :repo_id)
                ORDER BY score DESC
                LIMIT :top_n
            """)
            rows = session.execute(query, {
                "query": query_text,
                "repo_id": repo_id,
                "top_n": top_n,
            }).fetchall()
            return [
                {"chunk_id": r[0], "content": r[1], "start_line": r[2],
                 "end_line": r[3], "path": r[4], "type": r[5], "score": float(r[6])}
                for r in rows
            ]

    # ── Symbols ─────────────────────────────────────────────────────────

    def upsert_symbol(self, name: str, kind: str, file_path: str,
                      start_line: int = None, end_line: int = None,
                      signature: str = None, docstring: str = None,
                      repo_id: str = "default") -> Symbol:
        with self.get_session() as session:
            sym = session.query(Symbol).filter_by(
                name=name, kind=kind, file_path=file_path, start_line=start_line
            ).first()
            if sym:
                sym.end_line = end_line
                sym.signature = signature
                sym.docstring = docstring
            else:
                sym = Symbol(
                    name=name, kind=kind, file_path=file_path,
                    start_line=start_line, end_line=end_line,
                    signature=signature, docstring=docstring,
                    repo_id=repo_id,
                )
                session.add(sym)
            session.commit()
            session.refresh(sym)
            return sym

    def delete_symbols_for_file(self, file_path: str, repo_id: str = "default"):
        with self.get_session() as session:
            symbols = session.query(Symbol).filter_by(
                file_path=file_path, repo_id=repo_id
            ).all()
            sym_ids = [s.id for s in symbols]
            if sym_ids:
                session.query(Edge).filter(
                    (Edge.src_id.in_(sym_ids)) | (Edge.dst_id.in_(sym_ids))
                ).delete(synchronize_session=False)
                session.query(Symbol).filter(Symbol.id.in_(sym_ids)).delete(
                    synchronize_session=False
                )
            session.commit()

    def get_symbol_by_name(self, name: str, repo_id: Optional[str] = None) -> list[Symbol]:
        with self.get_session() as session:
            q = session.query(Symbol).filter_by(name=name)
            if repo_id:
                q = q.filter_by(repo_id=repo_id)
            return q.all()

    # ── Edges ───────────────────────────────────────────────────────────

    def upsert_edge(self, src_kind: str, src_id: int, dst_kind: str, dst_id: int,
                    edge_type: str, weight: float = 1.0):
        with self.get_session() as session:
            edge = session.query(Edge).filter_by(
                src_id=src_id, dst_id=dst_id, edge_type=edge_type
            ).first()
            if not edge:
                edge = Edge(
                    src_kind=src_kind, src_id=src_id,
                    dst_kind=dst_kind, dst_id=dst_id,
                    edge_type=edge_type, weight=weight,
                )
                session.add(edge)
                session.commit()

    def get_neighbors(self, symbol_id: int, depth: int = 1) -> list[dict]:
        """Get neighboring symbols in the graph (both directions)."""
        with self.get_session() as session:
            query = text("""
                WITH RECURSIVE graph AS (
                    -- Outgoing edges
                    SELECT e.dst_id AS neighbor_id, e.edge_type, 1 AS depth
                    FROM edges e WHERE e.src_id = :sym_id
                    UNION
                    -- Incoming edges
                    SELECT e.src_id AS neighbor_id, e.edge_type, 1 AS depth
                    FROM edges e WHERE e.dst_id = :sym_id
                    UNION
                    -- Recursive expansion
                    SELECT CASE WHEN e.src_id = g.neighbor_id THEN e.dst_id ELSE e.src_id END,
                           e.edge_type, g.depth + 1
                    FROM graph g
                    JOIN edges e ON (e.src_id = g.neighbor_id OR e.dst_id = g.neighbor_id)
                    WHERE g.depth < :depth
                )
                SELECT DISTINCT s.id, s.name, s.kind, s.file_path, s.start_line,
                       g.edge_type, g.depth
                FROM graph g
                JOIN symbols s ON s.id = g.neighbor_id
                ORDER BY g.depth, s.name
            """)
            rows = session.execute(query, {"sym_id": symbol_id, "depth": depth}).fetchall()
            return [
                {"id": r[0], "name": r[1], "kind": r[2], "file_path": r[3],
                 "start_line": r[4], "edge_type": r[5], "depth": r[6]}
                for r in rows
            ]

    def get_impact(self, symbol_id: int, depth: int = 2) -> list[dict]:
        """Get symbols that depend on this symbol (reverse deps — who calls/imports me?)."""
        with self.get_session() as session:
            query = text("""
                WITH RECURSIVE dependents AS (
                    SELECT e.src_id AS dep_id, e.edge_type, 1 AS depth
                    FROM edges e WHERE e.dst_id = :sym_id
                    UNION
                    SELECT e.src_id, e.edge_type, d.depth + 1
                    FROM dependents d
                    JOIN edges e ON e.dst_id = d.dep_id
                    WHERE d.depth < :depth
                )
                SELECT DISTINCT s.id, s.name, s.kind, s.file_path, s.start_line,
                       d.edge_type, d.depth
                FROM dependents d
                JOIN symbols s ON s.id = d.dep_id
                ORDER BY d.depth, s.name
            """)
            rows = session.execute(query, {"sym_id": symbol_id, "depth": depth}).fetchall()
            return [
                {"id": r[0], "name": r[1], "kind": r[2], "file_path": r[3],
                 "start_line": r[4], "edge_type": r[5], "depth": r[6]}
                for r in rows
            ]

    # ── Stats ───────────────────────────────────────────────────────────

    def get_stats(self, repo_id: Optional[str] = None) -> dict:
        with self.get_session() as session:
            def count(model, **filters):
                q = session.query(func.count(model.id))
                for k, v in filters.items():
                    q = q.filter(getattr(model, k) == v)
                return q.scalar()

            filters = {"repo_id": repo_id} if repo_id else {}
            sym_filters = {"repo_id": repo_id} if repo_id else {}

            return {
                "documents": count(Document, **filters),
                "chunks": session.query(func.count(Chunk.id)).scalar(),
                "symbols": count(Symbol, **sym_filters),
                "edges": session.query(func.count(Edge.id)).scalar(),
                "memory_facts": session.query(func.count(ProjectMemory.id)).scalar(),
                "chunks_with_embeddings": session.query(func.count(Chunk.id)).filter(
                    Chunk.embedding.isnot(None)
                ).scalar(),
            }
