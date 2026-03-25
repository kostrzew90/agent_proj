"""Repo indexer — scans files, parses, chunks, and stores in DB."""

from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Optional

from ai_repo.config import settings
from ai_repo.core.chunker import chunk_generic, chunk_python
from ai_repo.core.database import Database
from ai_repo.core.graph_builder import GraphBuilder
from ai_repo.parsers.dockerfile_parser import parse_dockerfile
from ai_repo.parsers.generic_parser import parse_generic
from ai_repo.parsers.python_parser import parse_python
from ai_repo.parsers.sql_parser import parse_sql
from ai_repo.parsers.yaml_parser import parse_yaml

logger = logging.getLogger(__name__)

# Map file extensions to parser functions
PARSER_MAP = {
    ".py": ("python", parse_python),
    ".yaml": ("yaml", parse_yaml),
    ".yml": ("yaml", parse_yaml),
    ".sql": ("sql", parse_sql),
    ".md": ("markdown", parse_generic),
    ".txt": ("text", parse_generic),
    ".json": ("json", parse_generic),
    ".toml": ("toml", parse_generic),
    ".cfg": ("config", parse_generic),
    ".ini": ("config", parse_generic),
    ".env": ("env", parse_generic),
    ".sh": ("shell", parse_generic),
    ".bash": ("shell", parse_generic),
    ".js": ("javascript", parse_generic),
    ".ts": ("typescript", parse_generic),
    ".jsx": ("javascript", parse_generic),
    ".tsx": ("typescript", parse_generic),
    ".go": ("go", parse_generic),
    ".rs": ("rust", parse_generic),
    ".java": ("java", parse_generic),
}


class Indexer:
    """Scans a repository, parses files, chunks content, and stores in DB."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()
        self.graph_builder = GraphBuilder(self.db)
        self.ignore_patterns = settings.indexing.ignore_patterns
        self.supported_extensions = settings.indexing.supported_extensions

    def index_repo(
        self,
        repo_path: str,
        repo_id: str = "default",
        incremental: bool = True,
    ) -> dict:
        """Index a repository. Returns stats dict."""
        import time as _time

        from ai_repo.core.metrics import emit_event, finish_indexing_job, start_indexing_job

        repo_path = os.path.abspath(repo_path)
        if not os.path.isdir(repo_path):
            raise ValueError(f"Not a directory: {repo_path}")

        logger.info(f"Indexing repo: {repo_path} (repo_id={repo_id}, incremental={incremental})")

        job_id = start_indexing_job(self.db, repo_id)
        t0 = _time.time()

        # Load gitignore patterns
        gitignore_patterns = self._load_gitignore(repo_path)

        # Scan files
        files = self._scan_files(repo_path, gitignore_patterns)
        logger.info(f"Found {len(files)} files to process")

        stats = {"scanned": len(files), "indexed": 0, "skipped": 0, "errors": 0}

        # Get existing documents for incremental check
        existing_docs = {}
        if incremental:
            for doc in self.db.get_all_documents(repo_id):
                existing_docs[doc.path] = (doc.hash, doc.mtime)

        # Track which paths are still present (for deletion of removed files)
        current_paths = set()

        for file_path in files:
            rel_path = os.path.relpath(file_path, repo_path).replace("\\", "/")
            current_paths.add(rel_path)

            try:
                file_stat = os.stat(file_path)
                file_mtime = file_stat.st_mtime
                file_hash = self._hash_file(file_path)

                # Incremental: skip unchanged files
                if incremental and rel_path in existing_docs:
                    old_hash, old_mtime = existing_docs[rel_path]
                    if old_hash == file_hash:
                        stats["skipped"] += 1
                        continue

                # Read file content
                source = self._read_file(file_path)
                if source is None:
                    stats["errors"] += 1
                    continue

                # Determine file type and parser
                ext = self._get_extension(file_path)
                file_type, parser_fn = PARSER_MAP.get(ext, ("generic", parse_generic))

                # Handle Dockerfile specially
                basename = os.path.basename(file_path).lower()
                if basename == "dockerfile" or basename.startswith("dockerfile."):
                    file_type = "dockerfile"
                    parser_fn = parse_dockerfile

                # Upsert document
                doc = self.db.upsert_document(
                    path=rel_path, file_type=file_type, file_hash=file_hash,
                    mtime=file_mtime, repo_id=repo_id,
                )

                # Chunk the file
                if file_type == "python":
                    chunks = chunk_python(source)
                else:
                    chunks = chunk_generic(source)

                # Store chunks
                chunk_dicts = [
                    {
                        "chunk_index": c.chunk_index,
                        "content": c.content,
                        "start_line": c.start_line,
                        "end_line": c.end_line,
                        "tokens": c.tokens,
                    }
                    for c in chunks
                ]
                self.db.insert_chunks(doc.id, chunk_dicts)

                # Parse for symbols and edges
                parse_result = parser_fn(rel_path, source)

                # Delete old symbols/edges for this file, then insert new
                self.db.delete_symbols_for_file(rel_path, repo_id)
                self.graph_builder.build_from_parse_result(
                    parse_result, rel_path, repo_id
                )

                stats["indexed"] += 1
                logger.debug(f"Indexed: {rel_path} ({len(chunks)} chunks)")

            except Exception as e:
                logger.error(f"Error indexing {file_path}: {e}")
                stats["errors"] += 1
                emit_event(
                    self.db, "indexer", "error",
                    f"Error indexing {rel_path}: {e}",
                    signature=type(e).__name__,
                )

        # Remove documents for files that no longer exist
        if incremental:
            for old_path in set(existing_docs.keys()) - current_paths:
                self.db.delete_document(old_path, repo_id)
                self.db.delete_symbols_for_file(old_path, repo_id)
                logger.debug(f"Removed deleted file: {old_path}")

        duration_ms = (_time.time() - t0) * 1000
        stats["duration_ms"] = duration_ms
        job_status = "failed" if stats["errors"] > 0 and stats["indexed"] == 0 else "completed"

        if job_id is not None:
            finish_indexing_job(self.db, job_id, stats, status=job_status)

        emit_event(
            self.db, "indexer", "info",
            f"Indexing complete: {stats['indexed']} indexed, "
            f"{stats['skipped']} skipped, {stats['errors']} errors "
            f"in {duration_ms:.0f}ms",
        )

        logger.info(
            f"Indexing complete: {stats['indexed']} indexed, "
            f"{stats['skipped']} skipped, {stats['errors']} errors"
        )
        return stats

    def _scan_files(self, repo_path: str, gitignore_patterns: list[str]) -> list[str]:
        """Recursively scan repository for supported files."""
        files = []
        for root, dirs, filenames in os.walk(repo_path):
            # Filter directories in-place
            dirs[:] = [
                d for d in dirs
                if d not in self.ignore_patterns
                and not d.startswith(".")
                and not self._matches_gitignore(d + "/", gitignore_patterns)
            ]

            for fname in filenames:
                ext = self._get_extension(fname)
                basename = fname.lower()

                # Support Dockerfiles without extension
                is_dockerfile = basename == "dockerfile" or basename.startswith("dockerfile.")
                is_supported = ext in self.supported_extensions or is_dockerfile

                if is_supported and not self._matches_gitignore(fname, gitignore_patterns):
                    files.append(os.path.join(root, fname))

        return files

    def _load_gitignore(self, repo_path: str) -> list[str]:
        """Load .gitignore patterns from repo root."""
        gitignore_path = os.path.join(repo_path, ".gitignore")
        patterns = []
        if os.path.exists(gitignore_path):
            try:
                with open(gitignore_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            patterns.append(line)
            except Exception:
                pass
        return patterns

    def _matches_gitignore(self, name: str, patterns: list[str]) -> bool:
        """Simple gitignore pattern matching."""
        for pattern in patterns:
            pattern = pattern.rstrip("/")
            if pattern in name:
                return True
            # Simple glob: *.ext
            if pattern.startswith("*") and name.endswith(pattern[1:]):
                return True
        return False

    @staticmethod
    def _hash_file(file_path: str) -> str:
        """SHA-256 hash of file contents."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for block in iter(lambda: f.read(8192), b""):
                sha256.update(block)
        return sha256.hexdigest()

    @staticmethod
    def _read_file(file_path: str) -> Optional[str]:
        """Read file as UTF-8 text, returns None on failure."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception as e:
            logger.warning(f"Cannot read {file_path}: {e}")
            return None

    @staticmethod
    def _get_extension(file_path: str) -> str:
        """Get lowercased file extension."""
        _, ext = os.path.splitext(file_path)
        return ext.lower()
