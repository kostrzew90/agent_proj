"""Graph builder — converts parser results into symbols + edges in DB."""

from __future__ import annotations

import logging
from typing import Optional

from ai_repo.core.database import Database
from ai_repo.parsers.python_parser import ParseResult

logger = logging.getLogger(__name__)


class GraphBuilder:
    """Takes ParseResult from parsers and builds the symbol/edge graph in DB."""

    def __init__(self, db: Database):
        self.db = db

    def build_from_parse_result(
        self,
        result: ParseResult,
        file_path: str,
        repo_id: str = "default",
    ):
        """Insert symbols and edges from a ParseResult."""
        # Phase 1: Insert all symbols and build a name→id mapping
        symbol_map: dict[tuple[str, str], int] = {}  # (name, kind) → symbol_id

        for sym in result.symbols:
            db_sym = self.db.upsert_symbol(
                name=sym.name,
                kind=sym.kind,
                file_path=sym.file_path,
                start_line=sym.start_line,
                end_line=sym.end_line,
                signature=sym.signature,
                docstring=sym.docstring,
                repo_id=repo_id,
            )
            symbol_map[(sym.name, sym.kind)] = db_sym.id

        # Phase 2: Insert edges — resolve names to IDs
        for edge in result.edges:
            src_id = self._resolve_symbol(
                edge.src_name, edge.src_kind, symbol_map, repo_id
            )
            dst_id = self._resolve_symbol(
                edge.dst_name, edge.dst_kind, symbol_map, repo_id
            )

            if src_id and dst_id and src_id != dst_id:
                self.db.upsert_edge(
                    src_kind=edge.src_kind,
                    src_id=src_id,
                    dst_kind=edge.dst_kind,
                    dst_id=dst_id,
                    edge_type=edge.edge_type,
                )

    def _resolve_symbol(
        self,
        name: str,
        kind: str,
        local_map: dict[tuple[str, str], int],
        repo_id: str,
    ) -> Optional[int]:
        """Resolve a symbol name to its ID — check local map first, then DB."""
        # Check exact match in local map
        if (name, kind) in local_map:
            return local_map[(name, kind)]

        # Check any kind match in local map
        for (n, k), sid in local_map.items():
            if n == name:
                return sid

        # Fallback: query DB
        symbols = self.db.get_symbol_by_name(name, repo_id)
        if symbols:
            return symbols[0].id

        return None
