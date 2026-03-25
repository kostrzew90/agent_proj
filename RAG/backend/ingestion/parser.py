"""
RAG System — Document Parser (Docling)
Converts PDF, DOCX, PPTX, images to markdown using Docling.
"""

import logging
from pathlib import Path
from dataclasses import dataclass, field

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions

from config import settings

logger = logging.getLogger("rag.parser")

# Supported file extensions mapped to Docling InputFormat
SUPPORTED_FORMATS: dict[str, InputFormat] = {
    ".pdf": InputFormat.PDF,
    ".docx": InputFormat.DOCX,
    ".pptx": InputFormat.PPTX,
    ".html": InputFormat.HTML,
    ".htm": InputFormat.HTML,
    ".md": InputFormat.MD,
    ".txt": InputFormat.MD,
    ".csv": InputFormat.CSV,
    ".png": InputFormat.IMAGE,
    ".jpg": InputFormat.IMAGE,
    ".jpeg": InputFormat.IMAGE,
    ".tiff": InputFormat.IMAGE,
    ".tif": InputFormat.IMAGE,
    ".bmp": InputFormat.IMAGE,
    ".rtf": InputFormat.HTML,
}


@dataclass
class ParseResult:
    """Result of document parsing."""
    markdown: str
    page_count: int | None = None
    title: str | None = None
    metadata: dict = field(default_factory=dict)
    success: bool = True
    error: str | None = None


def get_converter() -> DocumentConverter:
    """Create a configured DocumentConverter instance."""
    pdf_pipeline_options = PdfPipelineOptions(
        do_ocr=settings.docling.ocr_enabled,
        do_table_structure=True,
    )

    converter = DocumentConverter(
        allowed_formats=list(SUPPORTED_FORMATS.values()),
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_pipeline_options),
        },
    )
    return converter


# Module-level singleton (lazy init)
_converter: DocumentConverter | None = None


def _get_converter() -> DocumentConverter:
    global _converter
    if _converter is None:
        logger.info("Initializing Docling DocumentConverter...")
        _converter = get_converter()
        logger.info("Docling DocumentConverter ready.")
    return _converter


def is_supported(file_path: str | Path) -> bool:
    """Check if file format is supported by the parser."""
    ext = Path(file_path).suffix.lower()
    return ext in SUPPORTED_FORMATS


def parse_document(file_path: str | Path) -> ParseResult:
    """
    Parse a document file and return markdown content.

    Args:
        file_path: Path to the document file.

    Returns:
        ParseResult with markdown content and metadata.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        return ParseResult(markdown="", success=False, error=f"File not found: {file_path}")

    ext = file_path.suffix.lower()
    if ext not in SUPPORTED_FORMATS:
        return ParseResult(markdown="", success=False, error=f"Unsupported format: {ext}")

    # Plain text files — read directly, no Docling needed
    if ext in (".txt", ".md"):
        try:
            content = file_path.read_text(encoding="utf-8")
            return ParseResult(
                markdown=content,
                page_count=1,
                title=file_path.stem,
                metadata={"format": ext, "parser": "direct"},
            )
        except Exception as e:
            return ParseResult(markdown="", success=False, error=str(e))

    # All other formats — use Docling
    try:
        converter = _get_converter()
        result = converter.convert(str(file_path))

        doc = result.document
        markdown = doc.export_to_markdown()

        # Extract metadata
        page_count = None
        if hasattr(result, "pages") and result.pages:
            page_count = len(result.pages)

        title = None
        if hasattr(doc, "title") and doc.title:
            title = str(doc.title)

        metadata = {
            "format": ext,
            "parser": "docling",
            "status": str(result.status) if hasattr(result, "status") else "unknown",
        }

        logger.info(f"Parsed {file_path.name}: {len(markdown)} chars, {page_count or '?'} pages")

        return ParseResult(
            markdown=markdown,
            page_count=page_count,
            title=title,
            metadata=metadata,
        )

    except Exception as e:
        logger.error(f"Failed to parse {file_path.name}: {e}")
        return ParseResult(markdown="", success=False, error=str(e))
