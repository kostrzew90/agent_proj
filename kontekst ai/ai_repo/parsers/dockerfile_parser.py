"""Dockerfile parser — extracts FROM, COPY, RUN instructions."""

from __future__ import annotations

import re

from ai_repo.parsers.python_parser import EdgeInfo, ParseResult, SymbolInfo


def parse_dockerfile(file_path: str, source: str) -> ParseResult:
    """Parse Dockerfile and extract key instructions as symbols."""
    result = ParseResult()

    for i, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # FROM base_image
        m = re.match(r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?", stripped, re.IGNORECASE)
        if m:
            image = m.group(1)
            stage = m.group(2)
            name = f"stage:{stage}" if stage else f"base:{image}"
            result.symbols.append(SymbolInfo(
                name=name, kind="docker_stage", file_path=file_path,
                start_line=i, end_line=i, signature=image,
            ))
            continue

        # COPY / ADD
        m = re.match(r"^(COPY|ADD)\s+(.+)", stripped, re.IGNORECASE)
        if m:
            result.symbols.append(SymbolInfo(
                name=f"{m.group(1)}:{m.group(2).strip()}", kind="docker_copy",
                file_path=file_path, start_line=i, end_line=i,
            ))
            continue

        # EXPOSE
        m = re.match(r"^EXPOSE\s+(\d+)", stripped, re.IGNORECASE)
        if m:
            result.symbols.append(SymbolInfo(
                name=f"port:{m.group(1)}", kind="endpoint",
                file_path=file_path, start_line=i, end_line=i,
            ))
            continue

        # ENTRYPOINT / CMD
        m = re.match(r"^(ENTRYPOINT|CMD)\s+(.+)", stripped, re.IGNORECASE)
        if m:
            result.symbols.append(SymbolInfo(
                name=f"{m.group(1).lower()}", kind="entrypoint",
                file_path=file_path, start_line=i, end_line=i,
                signature=m.group(2).strip(),
            ))

    return result
