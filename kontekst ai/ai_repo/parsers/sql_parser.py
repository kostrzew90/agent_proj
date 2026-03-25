"""SQL parser — extracts CREATE TABLE, REFERENCES, indexes."""

from __future__ import annotations

import re

from ai_repo.parsers.python_parser import EdgeInfo, ParseResult, SymbolInfo


def parse_sql(file_path: str, source: str) -> ParseResult:
    """Parse SQL files and extract tables, columns, and foreign key references."""
    result = ParseResult()

    # CREATE TABLE
    for m in re.finditer(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
        source, re.IGNORECASE
    ):
        table_name = m.group(1)
        line = source[:m.start()].count("\n") + 1
        result.symbols.append(SymbolInfo(
            name=table_name, kind="table", file_path=file_path,
            start_line=line, end_line=line,
        ))

    # REFERENCES (foreign keys)
    for m in re.finditer(
        r"REFERENCES\s+(\w+)\s*\((\w+)\)",
        source, re.IGNORECASE
    ):
        ref_table = m.group(1)
        # Find which CREATE TABLE this belongs to
        preceding = source[:m.start()]
        tables = re.findall(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)",
                            preceding, re.IGNORECASE)
        if tables:
            src_table = tables[-1]
            result.edges.append(EdgeInfo(
                src_name=src_table, src_kind="table",
                dst_name=ref_table, dst_kind="table",
                edge_type="depends_on",
            ))

    # CREATE INDEX
    for m in re.finditer(
        r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s+ON\s+(\w+)",
        source, re.IGNORECASE
    ):
        idx_name = m.group(1)
        table_name = m.group(2)
        line = source[:m.start()].count("\n") + 1
        result.symbols.append(SymbolInfo(
            name=idx_name, kind="index", file_path=file_path,
            start_line=line, end_line=line, signature=f"ON {table_name}",
        ))

    return result
