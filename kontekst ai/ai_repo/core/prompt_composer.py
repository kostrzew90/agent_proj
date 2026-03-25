"""Prompt composer — builds system + user prompts from retrieval context."""

from __future__ import annotations

import logging
from typing import Optional

from ai_repo.core.database import Database

logger = logging.getLogger(__name__)

SYSTEM_TEMPLATE = """\
You are an expert code assistant with deep knowledge of the analyzed repository.

Rules:
- Answer questions based ONLY on the provided context (code chunks, graph relationships, project facts).
- When referencing code, always cite the source as `file_path:line_number`.
- If the context is insufficient to answer, say so explicitly — do not guess.
- Be concise and precise. Use code blocks with language tags for code examples.
- When explaining architecture, mention how components relate to each other using the graph context.
"""

USER_TEMPLATE = """\
## Question
{query}

{context_sections}
"""


class PromptComposer:
    """Builds final LLM prompts from retrieval results, graph context, and memory."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()

    def compose(
        self,
        query: str,
        retrieval_results: list[dict],
        memory_facts: list[dict] | None = None,
    ) -> tuple[str, str]:
        """Build system and user prompts from retrieval context.

        Args:
            query: User's question.
            retrieval_results: Chunks from retriever (with optional graph_neighbors).
            memory_facts: Project memory facts relevant to the query.

        Returns:
            (system_prompt, user_prompt) tuple.
        """
        sections: list[str] = []

        # Code chunks
        chunks_text = self._format_chunks(retrieval_results)
        if chunks_text:
            sections.append(f"## Relevant Code\n{chunks_text}")

        # Graph context
        graph_text = self._format_graph_context(retrieval_results)
        if graph_text:
            sections.append(f"## Related Symbols (Graph)\n{graph_text}")

        # Memory facts
        if memory_facts:
            memory_text = self._format_memory(memory_facts)
            if memory_text:
                sections.append(f"## Project Facts\n{memory_text}")

        # Risk analysis
        risk_text = self._format_risks(retrieval_results)
        if risk_text:
            sections.append(f"## Impact / Risk\n{risk_text}")

        context_sections = "\n\n".join(sections) if sections else "(No context available)"

        system_prompt = SYSTEM_TEMPLATE.strip()
        user_prompt = USER_TEMPLATE.format(
            query=query,
            context_sections=context_sections,
        ).strip()

        return system_prompt, user_prompt

    def _format_chunks(self, results: list[dict]) -> str:
        """Format retrieval chunks as numbered code blocks."""
        if not results:
            return ""

        parts: list[str] = []
        for i, r in enumerate(results, 1):
            path = r.get("path", "unknown")
            start = r.get("start_line", "?")
            end = r.get("end_line", "?")
            file_type = r.get("type", "")
            content = r.get("content", "").strip()
            score = r.get("rrf_score", r.get("score", 0))

            lang = file_type if file_type in ("python", "sql", "yaml", "json", "javascript", "typescript", "go", "rust", "java") else ""
            parts.append(
                f"### [{i}] `{path}:{start}-{end}` (score: {score:.4f})\n"
                f"```{lang}\n{content}\n```"
            )

        return "\n\n".join(parts)

    def _format_graph_context(self, results: list[dict]) -> str:
        """Format graph neighbors from retrieval results."""
        seen: set[str] = set()
        lines: list[str] = []

        for r in results:
            neighbors = r.get("graph_neighbors", [])
            for n in neighbors:
                key = f"{n['name']}:{n['kind']}"
                if key in seen:
                    continue
                seen.add(key)
                lines.append(
                    f"- **{n['name']}** ({n['kind']}) in `{n['file_path']}` "
                    f"— edge: {n['edge_type']}"
                )

        return "\n".join(lines)

    def _format_memory(self, facts: list[dict]) -> str:
        """Format project memory facts."""
        if not facts:
            return ""

        lines: list[str] = []
        for f in facts:
            key = f.get("key", "")
            value = f.get("value", "")
            confidence = f.get("confidence", 0)
            lines.append(f"- **{key}**: {value} (confidence: {confidence:.0%})")

        return "\n".join(lines)

    def _format_risks(self, results: list[dict]) -> str:
        """Identify high-impact symbols from graph context."""
        # Collect symbols that appear as neighbors in many different chunks
        symbol_refs: dict[str, set[str]] = {}  # symbol_name -> set of referencing paths

        for r in results:
            path = r.get("path", "")
            for n in r.get("graph_neighbors", []):
                name = n["name"]
                if name not in symbol_refs:
                    symbol_refs[name] = set()
                symbol_refs[name].add(path)

        # Symbols referenced from 3+ different files = high impact
        risky: list[tuple[str, int]] = [
            (name, len(paths))
            for name, paths in symbol_refs.items()
            if len(paths) >= 3
        ]
        risky.sort(key=lambda x: x[1], reverse=True)

        if not risky:
            return ""

        lines = ["Symbols with wide impact (referenced from multiple files):"]
        for name, count in risky[:10]:
            lines.append(f"- **{name}** — referenced from {count} files")

        return "\n".join(lines)
