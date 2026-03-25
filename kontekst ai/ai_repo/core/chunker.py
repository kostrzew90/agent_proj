"""Code-aware chunking — splits source into meaningful chunks."""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Approximate token count: ~4 chars per token for code
CHARS_PER_TOKEN = 4
DEFAULT_MAX_TOKENS = 512
DEFAULT_OVERLAP_TOKENS = 128


@dataclass
class ChunkData:
    chunk_index: int
    content: str
    start_line: int
    end_line: int
    tokens: int


def chunk_python(source: str, max_tokens: int = DEFAULT_MAX_TOKENS) -> list[ChunkData]:
    """Chunk Python source by classes and functions, with sliding window fallback."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _sliding_window(source, max_tokens)

    lines = source.splitlines(keepends=True)
    chunks: list[ChunkData] = []
    used_lines: set[int] = set()

    # Extract top-level classes and functions
    nodes = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", start)
            nodes.append((start, end))

    # Sort by start line
    nodes.sort(key=lambda x: x[0])

    chunk_idx = 0

    # Module-level code before first def/class
    if nodes:
        first_start = nodes[0][0]
        if first_start > 1:
            header = "".join(lines[:first_start - 1]).strip()
            if header:
                tokens = _estimate_tokens(header)
                if tokens > 0:
                    chunks.append(ChunkData(
                        chunk_index=chunk_idx, content=header,
                        start_line=1, end_line=first_start - 1,
                        tokens=tokens,
                    ))
                    chunk_idx += 1
                    used_lines.update(range(1, first_start))

    # Each class/function as a chunk
    for start, end in nodes:
        content = "".join(lines[start - 1:end]).strip()
        tokens = _estimate_tokens(content)

        if tokens <= max_tokens:
            chunks.append(ChunkData(
                chunk_index=chunk_idx, content=content,
                start_line=start, end_line=end, tokens=tokens,
            ))
            chunk_idx += 1
        else:
            # Large class/function → split with sliding window
            sub_chunks = _sliding_window(
                content, max_tokens, start_line_offset=start - 1
            )
            for sc in sub_chunks:
                sc.chunk_index = chunk_idx
                chunks.append(sc)
                chunk_idx += 1

        used_lines.update(range(start, end + 1))

    # Remaining module-level code between and after functions
    remaining_lines = []
    current_start = None
    for i in range(1, len(lines) + 1):
        if i not in used_lines:
            if current_start is None:
                current_start = i
        else:
            if current_start is not None:
                block = "".join(lines[current_start - 1:i - 1]).strip()
                if block:
                    tokens = _estimate_tokens(block)
                    if tokens > 0:
                        chunks.append(ChunkData(
                            chunk_index=chunk_idx, content=block,
                            start_line=current_start, end_line=i - 1,
                            tokens=tokens,
                        ))
                        chunk_idx += 1
                current_start = None

    # Tail
    if current_start is not None:
        block = "".join(lines[current_start - 1:]).strip()
        if block:
            tokens = _estimate_tokens(block)
            if tokens > 0:
                chunks.append(ChunkData(
                    chunk_index=chunk_idx, content=block,
                    start_line=current_start, end_line=len(lines),
                    tokens=tokens,
                ))

    return chunks


def chunk_generic(source: str, max_tokens: int = DEFAULT_MAX_TOKENS) -> list[ChunkData]:
    """Generic sliding window chunking for non-Python files."""
    return _sliding_window(source, max_tokens)


def _sliding_window(
    source: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    start_line_offset: int = 0,
) -> list[ChunkData]:
    """Split text with sliding window, respecting line boundaries."""
    lines = source.splitlines(keepends=True)
    if not lines:
        return []

    chunks: list[ChunkData] = []
    chunk_idx = 0
    current_lines: list[str] = []
    current_start = 1
    current_tokens = 0

    for i, line in enumerate(lines, start=1):
        line_tokens = _estimate_tokens(line)
        if current_tokens + line_tokens > max_tokens and current_lines:
            content = "".join(current_lines).strip()
            if content:
                chunks.append(ChunkData(
                    chunk_index=chunk_idx,
                    content=content,
                    start_line=current_start + start_line_offset,
                    end_line=(current_start + len(current_lines) - 1) + start_line_offset,
                    tokens=current_tokens,
                ))
                chunk_idx += 1

            # Overlap: keep last N tokens worth of lines
            overlap_lines = []
            overlap_tok = 0
            for ol in reversed(current_lines):
                t = _estimate_tokens(ol)
                if overlap_tok + t > overlap_tokens:
                    break
                overlap_lines.insert(0, ol)
                overlap_tok += t

            current_lines = overlap_lines
            current_start = i - len(overlap_lines)
            current_tokens = overlap_tok

        current_lines.append(line)
        current_tokens += line_tokens

    # Last chunk
    if current_lines:
        content = "".join(current_lines).strip()
        if content:
            chunks.append(ChunkData(
                chunk_index=chunk_idx,
                content=content,
                start_line=current_start + start_line_offset,
                end_line=(current_start + len(current_lines) - 1) + start_line_offset,
                tokens=current_tokens,
            ))

    return chunks


def _estimate_tokens(text: str) -> int:
    """Rough token estimate — ~4 chars per token for code."""
    return max(1, len(text) // CHARS_PER_TOKEN)
