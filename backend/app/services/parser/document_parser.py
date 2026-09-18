"""
HireLens — Document Parser

Text out of a PDF or DOCX, or a message explaining why not.

PDFs go through three extraction strategies in turn, so a file one library
chokes on still has two chances. Encoding is detected rather than assumed,
since resumes arrive from everywhere. DOCX tables are walked explicitly —
plenty of resumes put the whole employment history in one. A document that
yields too little text is refused with something the uploader can act on,
rather than analysed into a confident report about nothing.
"""

import io
import re
import logging
import zipfile
from app.core.exceptions import ParseError, UnsupportedFileType

logger = logging.getLogger("hirelens")

SUPPORTED_MIME = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}

# Only ever 60k characters are sent to the model, so there is no reason to
# hold more than that in memory while extracting. The slack is there so a
# genuinely long CV still reads normally rather than being cut mid-sentence.
MAX_TEXT_CHARS = 60_000
EXTRACT_STOP_CHARS = MAX_TEXT_CHARS * 2

# A DOCX is a ZIP, and the upload cap applies to the COMPRESSED bytes, so the
# size of the file says nothing about the size of its contents. A 380KB archive
# that unpacks to 194MB has a valid signature, sits well under the upload
# limit, and contains perfectly well-formed XML; decompressing it cost 531MB of
# resident memory on one request when measured, which on a 512MB instance is an
# OOM kill that takes the API down for everyone rather than failing one upload.
# The declared uncompressed size is read from the archive directory and checked
# before anything is decompressed. A real CV's XML is a fraction of this.
MAX_DOCX_UNCOMPRESSED_MB = 25


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


def check_docx_expansion(file_bytes: bytes) -> None:
    """
    Refuse a DOCX that unpacks to far more than any CV could contain.

    The archive's own directory is read here — no entry is decompressed —
    so this costs nothing and runs before the file reaches a parser that
    would happily allocate every byte of it.
    """
    cap = MAX_DOCX_UNCOMPRESSED_MB * 1024 * 1024
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
            declared = sum(max(0, info.file_size) for info in archive.infolist())
    except zipfile.BadZipFile:
        raise UnsupportedFileType("this DOCX file is corrupted and could not be opened")

    if declared > cap:
        logger.warning(
            f"Rejected DOCX that unpacks to {declared / 1024 / 1024:.0f}MB "
            f"from {len(file_bytes) / 1024:.0f}KB (cap {MAX_DOCX_UNCOMPRESSED_MB}MB)"
        )
        raise UnsupportedFileType(
            f"this DOCX unpacks to {declared / 1024 / 1024:.0f}MB, which is far larger "
            f"than a CV should be (limit {MAX_DOCX_UNCOMPRESSED_MB}MB)"
        )


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
    if fmt == "docx":
        check_docx_expansion(file_bytes)

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

    if char_count > MAX_TEXT_CHARS:
        logger.warning(f"Text very long ({char_count} chars) — truncating to 60k")
        text = text[:MAX_TEXT_CHARS]

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
        collected = 0
        for page_layout in extract_pages(io.BytesIO(data)):
            if collected > EXTRACT_STOP_CHARS:
                logger.warning("PDF text exceeded the extraction cap — stopping early")
                break
            for element in page_layout:
                if isinstance(element, LTTextContainer):
                    chunk = element.get_text()
                    parts.append(chunk)
                    collected += len(chunk)
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
        collected = 0

        for element in doc.element.body:
            # A document can be legitimately long, or engineered to be. Either
            # way only MAX_TEXT_CHARS is ever used, so there is nothing to gain
            # by holding the rest.
            if collected > EXTRACT_STOP_CHARS:
                logger.warning("DOCX text exceeded the extraction cap — stopping early")
                break

            tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

            if tag == "p":
                try:
                    para = docx.text.paragraph.Paragraph(element, doc)
                    t = para.text.strip()
                    if t:
                        parts.append(t)
                        collected += len(t)
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
                            row_text = " | ".join(cells)
                            parts.append(row_text)
                            collected += len(row_text)
                except Exception:
                    pass

        return "\n".join(parts)

    except ParseError:
        raise
    except Exception as e:
        # The underlying message is a library internal ("'lxml.etree._Element'
        # object has no attribute 'overrides'"), which tells a recruiter
        # nothing and exposes what we run. Log it, say something useful.
        logger.warning(f"DOCX extraction failed: {e}")
        raise ParseError(
            "Could not read this DOCX file. It may be corrupted, password-protected, "
            "or saved in an older Word format — try re-saving it as .docx or a PDF."
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
