import pytest
from app.services.parser.document_parser import check_magic_bytes
from app.core.exceptions import UnsupportedFileType


def test_magic_bytes_valid_pdf():
    pdf_bytes = b"%PDF-1.4 header contents..."
    check_magic_bytes(pdf_bytes, "pdf")  # Should not raise


def test_magic_bytes_invalid_pdf():
    invalid_pdf = b"NOT_A_PDF header"
    with pytest.raises(UnsupportedFileType) as exc_info:
        check_magic_bytes(invalid_pdf, "pdf")
    assert "invalid PDF file signature" in str(exc_info.value)


def test_magic_bytes_valid_docx():
    docx_bytes = b"PK\x03\x04 archive contents..."
    check_magic_bytes(docx_bytes, "docx")  # Should not raise


def test_magic_bytes_invalid_docx():
    invalid_docx = b"NOT_ZIP header"
    with pytest.raises(UnsupportedFileType) as exc_info:
        check_magic_bytes(invalid_docx, "docx")
    assert "invalid DOCX file signature" in str(exc_info.value)
