"""Generic parser — handles requirements.txt, .env, markdown, and other text files."""

from __future__ import annotations

import re

from ai_repo.parsers.python_parser import EdgeInfo, ParseResult, SymbolInfo


def parse_generic(file_path: str, source: str) -> ParseResult:
    """Parse generic text files and extract basic symbols."""
    result = ParseResult()

    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    basename = file_path.rsplit("/", 1)[-1].lower() if "/" in file_path else file_path.lower()

    if basename == "requirements.txt" or basename.endswith("requirements.txt"):
        result = _parse_requirements(file_path, source)
    elif ext == "env" or basename.startswith(".env"):
        result = _parse_env(file_path, source)
    elif ext == "md":
        result = _parse_markdown(file_path, source)
    elif ext in ("toml", "cfg", "ini"):
        result = _parse_config_sections(file_path, source)

    return result


def _parse_requirements(file_path: str, source: str) -> ParseResult:
    result = ParseResult()
    for i, line in enumerate(source.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # Extract package name (before any version specifier)
        pkg = re.split(r"[>=<!;\[\]]", line)[0].strip()
        if pkg:
            result.symbols.append(SymbolInfo(
                name=pkg, kind="dependency", file_path=file_path,
                start_line=i, end_line=i, signature=line,
            ))
    return result


def _parse_env(file_path: str, source: str) -> ParseResult:
    result = ParseResult()
    for i, line in enumerate(source.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key = line.split("=", 1)[0].strip()
            result.symbols.append(SymbolInfo(
                name=key, kind="variable", file_path=file_path,
                start_line=i, end_line=i,
            ))
    return result


def _parse_markdown(file_path: str, source: str) -> ParseResult:
    result = ParseResult()
    for i, line in enumerate(source.splitlines(), start=1):
        m = re.match(r"^(#{1,3})\s+(.+)", line)
        if m:
            level = len(m.group(1))
            heading = m.group(2).strip()
            result.symbols.append(SymbolInfo(
                name=heading, kind=f"heading_h{level}", file_path=file_path,
                start_line=i, end_line=i,
            ))
    return result


def _parse_config_sections(file_path: str, source: str) -> ParseResult:
    result = ParseResult()
    for i, line in enumerate(source.splitlines(), start=1):
        # [section] headers
        m = re.match(r"^\[([^\]]+)\]", line.strip())
        if m:
            result.symbols.append(SymbolInfo(
                name=m.group(1), kind="config_section", file_path=file_path,
                start_line=i, end_line=i,
            ))
    return result
