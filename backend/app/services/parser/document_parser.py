"""
HireLens — Document Parser
Fixed:
- Better encoding handling for international resumes
- Fallback chain for corrupted PDFs
- DOCX table extraction improved
- Minimum text validation with helpful error
"""

import io
import re
import logging
from app.core.exceptions import ParseError, UnsupportedFileType

logger = logging.getLogger("hirelens")

SUPPORTED_MIME = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}


def extract_text(file_bytes: bytes, mime_type: str, filename: str = "") -> str:
    """
    Extract plain text from PDF or DOCX bytes.
    
    Raises:
        UnsupportedFileType: If format not supported
        ParseError: If extraction fails or text too short
    """
    if not file_bytes:
        raise ParseError("File is empty.")

    # Determine format
    fmt = SUPPORTED_MIME.get(mime_type)
    if not fmt:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext == "pdf":
            fmt = "pdf"
        elif ext == "docx":
            fmt = "docx"

    if not fmt:
        raise UnsupportedFileType(mime_type or filename or "unknown")

    logger.info(f"Parsing {fmt.upper()} | size={len(file_bytes)/1024:.0f}KB | file={filename}")

    if fmt == "pdf":
        text = _parse_pdf(file_bytes)
    else:
        text = _parse_docx(file_bytes)

    text = _clean_text(text)

    # Validate extracted text
    stripped = text.strip()
    char_count = len(stripped)

    if char_count < 50:
        if fmt == "pdf":
            raise ParseError(
                "Could not extract text from this PDF. "
                "This usually means it's a scanned/image PDF. "
                "Please use a text-selectable PDF or convert to DOCX."
            )
        else:
            raise ParseError(
                "Could not extract text from this DOCX file. "
                "The file may be corrupted or empty."
            )

    if char_count > 60_000:
        logger.warning(f"Text very long ({char_count} chars) — truncating to 60k")
        text = text[:60_000]

    logger.info(f"Extracted {len(text)} chars successfully")
    return text


def _parse_pdf(data: bytes) -> str:
    """PDF extraction with multiple fallback strategies."""
    # Strategy 1: Layout-aware (best for multi-column resumes)
    try:
        from pdfminer.high_level import extract_text_to_fp
        from pdfminer.layout import LAParams

        out = io.StringIO()
        laparams = LAParams(
            line_overlap=0.5,
            char_margin=2.0,
            word_margin=0.1,
            boxes_flow=0.5,
            detect_vertical=False,
        )
        extract_text_to_fp(
            io.BytesIO(data), out,
            laparams=laparams,
            output_type="text",
            codec="utf-8",
        )
        text = out.getvalue()
        if text and len(text.strip()) > 50:
            return text
    except Exception as e:
        logger.warning(f"Layout PDF extraction failed: {e}")

    # Strategy 2: Basic extraction
    try:
        from pdfminer.high_level import extract_text
        text = extract_text(io.BytesIO(data))
        if text and len(text.strip()) > 50:
            return text
    except Exception as e:
        logger.warning(f"Basic PDF extraction failed: {e}")

    # Strategy 3: Page-by-page with error recovery
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTTextContainer

        parts = []
        for page_layout in extract_pages(io.BytesIO(data)):
            for element in page_layout:
                if isinstance(element, LTTextContainer):
                    parts.append(element.get_text())
        text = "\n".join(parts)
        if text and len(text.strip()) > 50:
            return text
    except Exception as e:
        logger.warning(f"Page-by-page PDF extraction failed: {e}")

    raise ParseError(
        "Could not extract text from this PDF after multiple attempts. "
        "Please ensure it's a text-selectable PDF (not scanned)."
    )


def _parse_docx(data: bytes) -> str:
    """DOCX extraction with paragraph and table support."""
    try:
        import docx

        doc = docx.Document(io.BytesIO(data))
        parts = []

        for element in doc.element.body:
            tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

            if tag == "p":
                try:
                    para = docx.text.paragraph.Paragraph(element, doc)
                    t = para.text.strip()
                    if t:
                        parts.append(t)
                except Exception:
                    pass

            elif tag == "tbl":
                try:
                    table = docx.table.Table(element, doc)
                    for row in table.rows:
                        cells = []
                        for cell in row.cells:
                            ct = cell.text.strip()
                            if ct:
                                cells.append(ct)
                        if cells:
                            parts.append(" | ".join(cells))
                except Exception:
                    pass

        return "\n".join(parts)

    except Exception as e:
        raise ParseError(f"DOCX extraction failed: {str(e)}")


def _clean_text(text: str) -> str:
    """Clean extracted text while preserving structure."""
    if not text:
        return ""

    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Remove excessive blank lines (keep max 2 consecutive)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Normalize spaces (but preserve newlines)
    lines = [re.sub(r"[ \t]{2,}", " ", line) for line in text.split("\n")]
    text = "\n".join(lines)

    # Remove non-printable characters (keep basic unicode for international names)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    return text.strip()
