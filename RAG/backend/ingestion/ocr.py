"""
RAG System — OCR via Docling
Handles image OCR using Docling's built-in pipeline (SmolDocling / EasyOCR).
Images are processed as InputFormat.IMAGE through the same Docling converter.
"""

import logging
from pathlib import Path

from ingestion.parser import parse_document, ParseResult, SUPPORTED_FORMATS
from docling.datamodel.base_models import InputFormat

logger = logging.getLogger("rag.ocr")

# Image extensions supported for OCR
IMAGE_EXTENSIONS = {
    ext for ext, fmt in SUPPORTED_FORMATS.items()
    if fmt == InputFormat.IMAGE
}


def is_image(file_path: str | Path) -> bool:
    """Check if a file is an image that can be OCR'd."""
    return Path(file_path).suffix.lower() in IMAGE_EXTENSIONS


def ocr_image(file_path: str | Path) -> ParseResult:
    """
    Perform OCR on an image file using Docling.

    Docling handles IMAGE format natively — it runs OCR, detects layout,
    tables, formulas, and outputs structured markdown.

    Args:
        file_path: Path to image file (PNG, JPG, TIFF, BMP).

    Returns:
        ParseResult with extracted markdown text.
    """
    file_path = Path(file_path)

    if not is_image(file_path):
        return ParseResult(
            markdown="",
            success=False,
            error=f"Not an image file: {file_path.suffix}",
        )

    logger.info(f"Running OCR on image: {file_path.name}")
    result = parse_document(file_path)

    if result.success:
        result.metadata["chunk_type"] = "image_ocr"
        logger.info(f"OCR complete: {file_path.name} → {len(result.markdown)} chars")
    else:
        logger.error(f"OCR failed for {file_path.name}: {result.error}")

    return result
