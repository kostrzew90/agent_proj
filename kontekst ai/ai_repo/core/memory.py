"""Project memory — CRUD + auto-bootstrap from indexed repo."""

from __future__ import annotations

import json
import logging
from typing import Optional

from ai_repo.config import settings
from ai_repo.core.database import Database, ProjectMemory, Symbol

logger = logging.getLogger(__name__)


class MemoryManager:
    """Manage project memory facts (key-value with confidence and tags)."""

    def __init__(self, db: Optional[Database] = None, llm=None):
        """
        Args:
            db: Database instance.
            llm: Optional LLMClient for auto-bootstrap (lazy import if needed).
        """
        self.db = db or Database()
        self._llm = llm

    @property
    def llm(self):
        if self._llm is None:
            from ai_repo.core.llm import LLMClient
            self._llm = LLMClient()
        return self._llm

    # ── CRUD ─────────────────────────────────────────────────────────────

    def set_fact(
        self,
        key: str,
        value: str,
        confidence: float = None,
        tags: list[str] | None = None,
        source: str | None = None,
    ) -> dict:
        """Insert or update a memory fact."""
        confidence = confidence if confidence is not None else settings.memory.default_confidence
        with self.db.get_session() as session:
            fact = session.query(ProjectMemory).filter_by(key=key).first()
            if fact:
                fact.value = value
                fact.confidence = confidence
                if tags is not None:
                    fact.tags = tags
                if source is not None:
                    fact.source = source
            else:
                fact = ProjectMemory(
                    key=key,
                    value=value,
                    confidence=confidence,
                    tags=tags or [],
                    source=source,
                )
                session.add(fact)
            session.commit()
            session.refresh(fact)
            return self._fact_to_dict(fact)

    def get_fact(self, key: str) -> Optional[dict]:
        """Get a single fact by key."""
        with self.db.get_session() as session:
            fact = session.query(ProjectMemory).filter_by(key=key).first()
            return self._fact_to_dict(fact) if fact else None

    def search_facts(
        self,
        query: str = "",
        tags: list[str] | None = None,
    ) -> list[dict]:
        """Search facts by text (key/value ILIKE) and/or tags overlap."""
        with self.db.get_session() as session:
            q = session.query(ProjectMemory)

            if query:
                pattern = f"%{query}%"
                q = q.filter(
                    ProjectMemory.key.ilike(pattern)
                    | ProjectMemory.value.ilike(pattern)
                )

            if tags:
                q = q.filter(ProjectMemory.tags.overlap(tags))

            results = q.order_by(ProjectMemory.confidence.desc()).all()
            return [self._fact_to_dict(f) for f in results]

    def get_all_facts(self) -> list[dict]:
        """Return all memory facts."""
        with self.db.get_session() as session:
            facts = session.query(ProjectMemory).order_by(ProjectMemory.key).all()
            return [self._fact_to_dict(f) for f in facts]

    def delete_fact(self, key: str) -> bool:
        """Delete a fact by key. Returns True if deleted."""
        with self.db.get_session() as session:
            count = session.query(ProjectMemory).filter_by(key=key).delete()
            session.commit()
            return count > 0

    # ── Auto-bootstrap ───────────────────────────────────────────────────

    async def auto_bootstrap(self, repo_id: str = "default"):
        """Generate project facts from indexed symbols and files.

        After initial indexing, this collects:
        - File list (by type)
        - Symbols (modules, classes, functions, tables, services)
        - DB schemas (tables + relationships)
        - Entrypoints

        Then asks LLM to generate key-value facts and stores them.
        """
        logger.info(f"Auto-bootstrapping memory for repo_id={repo_id}")

        with self.db.get_session() as session:
            # Gather symbols by kind
            symbols = session.query(Symbol).filter_by(repo_id=repo_id).all()

            by_kind: dict[str, list[str]] = {}
            for s in symbols:
                by_kind.setdefault(s.kind, []).append(
                    f"{s.name} ({s.file_path}:{s.start_line or '?'})"
                )

            # Gather file types
            from ai_repo.core.database import Document
            docs = session.query(Document).filter_by(repo_id=repo_id).all()
            file_types: dict[str, int] = {}
            for d in docs:
                file_types[d.type] = file_types.get(d.type, 0) + 1

        # Build summary for LLM
        summary_parts = [
            f"Repository '{repo_id}' has {len(docs)} files:",
            "",
            "File types: " + ", ".join(f"{t}: {c}" for t, c in sorted(file_types.items())),
            "",
        ]

        for kind in ["class", "function", "table", "service", "entrypoint", "import"]:
            items = by_kind.get(kind, [])
            if items:
                summary_parts.append(f"{kind.title()}s ({len(items)}):")
                for item in items[:30]:  # Cap at 30 per kind
                    summary_parts.append(f"  - {item}")
                if len(items) > 30:
                    summary_parts.append(f"  ... and {len(items) - 30} more")
                summary_parts.append("")

        summary = "\n".join(summary_parts)

        prompt = f"""\
Analyze this repository structure and generate key project facts as JSON.

{summary}

Return a JSON array of objects, each with:
- "key": short identifier (e.g. "main_language", "architecture_pattern", "db_tables", "entry_point")
- "value": concise description
- "tags": list of relevant tags (e.g. ["architecture"], ["database"], ["api"])

Generate 5-15 facts covering: main language, architecture pattern, key modules, database tables, entry points, external dependencies. Only return valid JSON array, no other text."""

        try:
            response = await self.llm.generate(
                prompt=prompt,
                system="You are a code analysis assistant. Return only valid JSON.",
                temperature=0.2,
            )

            # Parse JSON from response (handle markdown code blocks)
            json_str = response.strip()
            if json_str.startswith("```"):
                lines = json_str.split("\n")
                json_str = "\n".join(lines[1:-1])

            facts = json.loads(json_str)

            stored = 0
            for fact in facts:
                if isinstance(fact, dict) and "key" in fact and "value" in fact:
                    self.set_fact(
                        key=fact["key"],
                        value=fact["value"],
                        confidence=0.7,
                        tags=fact.get("tags", []),
                        source="auto-bootstrap",
                    )
                    stored += 1

            logger.info(f"Auto-bootstrap: stored {stored} facts")
            return stored

        except json.JSONDecodeError as e:
            logger.error(f"Auto-bootstrap: failed to parse LLM response as JSON: {e}")
            return 0
        except Exception as e:
            logger.error(f"Auto-bootstrap failed: {e}")
            return 0

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _fact_to_dict(fact: ProjectMemory) -> dict:
        return {
            "id": fact.id,
            "key": fact.key,
            "value": fact.value,
            "confidence": fact.confidence,
            "tags": fact.tags or [],
            "source": fact.source,
            "updated_at": str(fact.updated_at) if fact.updated_at else None,
        }
