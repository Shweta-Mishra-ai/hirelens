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
import zipfile
import logging
from app.core.exceptions import ParseError, UnsupportedFileType

logger = logging.getLogger("hirelens")

# A DOCX is a ZIP archive, and the upload cap only limits the COMPRESSED
# size. Highly repetitive XML compresses at ratios in the thousands, so a
# 10MB upload that passes every existing check can expand to gigabytes the
# moment python-docx reads word/document.xml — enough to OOM-kill a
# single-worker container and take the API down for everyone.
#
# Both limits are needed. The absolute cap catches a large expansion; the
# ratio catches a small file with an extreme one. Sizes come from the ZIP
# central directory, so nothing is decompressed to perform the check.
MAX_DOCX_UNCOMPRESSED_BYTES = 80 * 1024 * 1024
MAX_DOCX_COMPRESSION_RATIO = 200


def _reject_zip_bomb(data: bytes) -> None:
    """Refuse a DOCX whose declared expansion is implausible for a resume."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
    except zipfile.BadZipFile:
        raise UnsupportedFileType("corrupted DOCX (not a readable ZIP archive)")

    total_uncompressed = sum(e.file_size for e in entries)
    if total_uncompressed > MAX_DOCX_UNCOMPRESSED_BYTES:
        logger.warning(
            f"Rejected DOCX: declares {total_uncompressed / 1024 / 1024:.0f}MB uncompressed "
            f"from {len(data) / 1024:.0f}KB compressed"
        )
        raise UnsupportedFileType("DOCX contents are too large to process")

    ratio = total_uncompressed / max(1, len(data))
    if ratio > MAX_DOCX_COMPRESSION_RATIO:
        logger.warning(f"Rejected DOCX: compression ratio {ratio:.0f}x")
        raise UnsupportedFileType("DOCX compression ratio is implausible for a document")

SUPPORTED_MIME = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}


def check_magic_bytes(file_bytes: bytes, fmt: str) -> None:
    """Validate binary header magic bytes to reject spoofed or corrupted files."""
    if not file_bytes:
        raise UnsupportedFileType("empty file")
    if fmt == "pdf":
        if not file_bytes.startswith(b"%PDF"):
            raise UnsupportedFileType("invalid PDF file signature (missing %PDF header)")
    elif fmt == "docx":
        if not file_bytes.startswith(b"PK\x03\x04"):
            raise UnsupportedFileType("invalid DOCX file signature (missing ZIP PK header)")


def extract_text(file_bytes: bytes, mime_type: str, filename: str = "") -> str:
    """
    Extract plain text from PDF or DOCX bytes.
    
    Raises:
        UnsupportedFileType: If format not supported or header invalid
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

    # Verify magic bytes
    check_magic_bytes(file_bytes, fmt)

    # ...and, for DOCX, that the archive does not claim to expand to
    # something that would exhaust memory once python-docx reads it.
    if fmt == "docx":
        _reject_zip_bomb(file_bytes)

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

    except ParseError:
        raise
    except Exception as e:
        # The underlying exception can carry library internals and temporary
        # paths, and this message is surfaced to the user through the job
        # status. Log the detail; tell the user something actionable.
        logger.warning(f"DOCX extraction failed: {e}")
        raise ParseError(
            "Could not read this DOCX file. It may be corrupted, password-protected, "
            "or saved in an older .doc format — try re-saving it as .docx or PDF."
        )


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
