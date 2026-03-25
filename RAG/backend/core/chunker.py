"""
RAG System — Document-Aware Chunker
Splits markdown content into chunks respecting document structure.
"""

import logging
import re
from dataclasses import dataclass, field

import tiktoken

from config import settings

logger = logging.getLogger("rag.chunker")

# Tokenizer for counting tokens
_enc = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Count tokens using tiktoken."""
    return len(_enc.encode(text))


@dataclass
class Chunk:
    """A single document chunk."""
    content: str
    chunk_index: int
    token_count: int
    section_title: str | None = None
    page_number: int | None = None
    chunk_type: str = "text"  # text, table, code, image_ocr
    metadata: dict = field(default_factory=dict)


def _detect_chunk_type(text: str) -> str:
    """Detect the type of content in a chunk."""
    stripped = text.strip()
    if stripped.startswith("|") and "\n|" in stripped:
        return "table"
    if stripped.startswith("```") or stripped.startswith("    "):
        return "code"
    return "text"


def _split_by_headings(markdown: str) -> list[tuple[str | None, str]]:
    """
    Split markdown into sections by headings.
    Returns list of (heading, content) tuples.
    """
    # Match markdown headings (# through ####)
    heading_pattern = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)

    sections: list[tuple[str | None, str]] = []
    last_end = 0
    last_heading = None

    for match in heading_pattern.finditer(markdown):
        # Content before this heading belongs to previous section
        content = markdown[last_end:match.start()].strip()
        if content:
            sections.append((last_heading, content))

        last_heading = match.group(2).strip()
        last_end = match.end()

    # Remaining content after last heading
    remaining = markdown[last_end:].strip()
    if remaining:
        sections.append((last_heading, remaining))

    # If no headings found, return entire content as one section
    if not sections:
        sections = [(None, markdown.strip())]

    return sections


def _split_large_text(
    text: str,
    max_tokens: int,
    overlap_tokens: int,
) -> list[str]:
    """
    Split a large text block into smaller pieces at paragraph boundaries.
    Falls back to sentence boundaries, then hard split.
    """
    if count_tokens(text) <= max_tokens:
        return [text]

    # Try splitting by paragraphs (double newline)
    paragraphs = re.split(r"\n\n+", text)

    chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens = count_tokens(para)

        # Single paragraph exceeds max — split by sentences
        if para_tokens > max_tokens:
            # Flush current buffer
            if current_parts:
                chunks.append("\n\n".join(current_parts))
                current_parts = []
                current_tokens = 0

            sentences = re.split(r"(?<=[.!?])\s+", para)
            for sent in sentences:
                sent_tokens = count_tokens(sent)
                if current_tokens + sent_tokens > max_tokens and current_parts:
                    chunks.append(" ".join(current_parts))
                    # Keep overlap
                    overlap_text = " ".join(current_parts[-2:]) if len(current_parts) >= 2 else ""
                    current_parts = [overlap_text] if overlap_text else []
                    current_tokens = count_tokens(overlap_text) if overlap_text else 0
                current_parts.append(sent)
                current_tokens += sent_tokens
            continue

        if current_tokens + para_tokens > max_tokens and current_parts:
            chunks.append("\n\n".join(current_parts))
            # Overlap: keep last paragraph
            overlap_part = current_parts[-1] if current_parts else ""
            current_parts = [overlap_part] if overlap_part and count_tokens(overlap_part) <= overlap_tokens else []
            current_tokens = count_tokens(current_parts[0]) if current_parts else 0

        current_parts.append(para)
        current_tokens += para_tokens

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks


def chunk_document(
    markdown: str,
    file_type: str = "pdf",
) -> list[Chunk]:
    """
    Split markdown content into chunks respecting document structure.

    Strategy:
    1. Split by headings (sections)
    2. If a section is too large, split by paragraphs with overlap
    3. Skip chunks that are too small (< min_size tokens)

    Args:
        markdown: Markdown content from parser.
        file_type: Original file type for strategy selection.

    Returns:
        List of Chunk objects ready for embedding.
    """
    target_size = settings.chunking.size
    max_size = settings.chunking.max_size
    min_size = settings.chunking.min_size
    overlap = settings.chunking.overlap

    if not markdown or not markdown.strip():
        return []

    sections = _split_by_headings(markdown)
    chunks: list[Chunk] = []
    chunk_index = 0

    for section_title, section_content in sections:
        section_tokens = count_tokens(section_content)

        # Section fits in one chunk
        if section_tokens <= max_size:
            if section_tokens >= min_size:
                # Prepend heading for context
                content = f"## {section_title}\n\n{section_content}" if section_title else section_content
                chunks.append(Chunk(
                    content=content,
                    chunk_index=chunk_index,
                    token_count=count_tokens(content),
                    section_title=section_title,
                    chunk_type=_detect_chunk_type(section_content),
                ))
                chunk_index += 1
            continue

        # Section too large — split into sub-chunks
        sub_texts = _split_large_text(section_content, target_size, overlap)
        for sub_text in sub_texts:
            token_count = count_tokens(sub_text)
            if token_count < min_size:
                continue

            content = f"## {section_title}\n\n{sub_text}" if section_title else sub_text
            chunks.append(Chunk(
                content=content,
                chunk_index=chunk_index,
                token_count=count_tokens(content),
                section_title=section_title,
                chunk_type=_detect_chunk_type(sub_text),
            ))
            chunk_index += 1

    logger.info(f"Chunked document into {len(chunks)} chunks (type={file_type})")
    return chunks
