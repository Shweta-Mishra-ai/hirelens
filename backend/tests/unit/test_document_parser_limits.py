"""
What the CV parser does with a file that is not a CV.

The one that matters: a DOCX is a ZIP, and the 10MB upload cap applies to
the COMPRESSED bytes. A 380KB archive that unpacks to 194MB passed every
check this parser made — valid PK signature, far under the size limit,
perfectly well-formed XML — and cost 531MB of resident memory on a single
request when measured. On a 512MB instance that is an OOM kill, and an OOM
kill takes the API down for every user rather than failing one upload. The
archive directory is now read before anything is decompressed.
"""

import io
import zipfile

import pytest

from app.core.exceptions import ParseError, UnsupportedFileType
from app.services.parser.document_parser import (
    MAX_DOCX_UNCOMPRESSED_MB,
    MAX_TEXT_CHARS,
    check_docx_expansion,
    extract_text,
)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

CONTENT_TYPES = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

RELS = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

HEAD = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
)
TAIL = b"</w:body></w:document>"


def paragraph(text: bytes) -> bytes:
    return b"<w:p><w:r><w:t>" + text + b"</w:t></w:r></w:p>"


def make_docx(body: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", RELS)
        archive.writestr("word/document.xml", HEAD + body + TAIL)
    return buf.getvalue()


CV_TEXT = (
    b"Anita Rao - Senior Backend Engineer. Seven years building payments "
    b"infrastructure in Python and Go. Led the migration of a monolithic "
    b"ledger to event-driven services at Acme Payments."
)


class TestNormalFiles:
    def test_a_real_docx_parses(self):
        text = extract_text(make_docx(paragraph(CV_TEXT)), DOCX_MIME, "anita.docx")
        assert "Anita Rao" in text
        assert "payments infrastructure" in text

    def test_a_docx_is_recognised_by_extension_when_the_mime_is_generic(self):
        text = extract_text(make_docx(paragraph(CV_TEXT)), "application/octet-stream", "anita.docx")
        assert "Anita Rao" in text

    def test_a_long_but_genuine_cv_is_truncated_not_refused(self):
        body = paragraph(b"A" * 2000) * 200
        text = extract_text(make_docx(body), DOCX_MIME, "long.docx")
        assert len(text) == MAX_TEXT_CHARS


class TestTheZipBomb:
    @pytest.fixture(scope="class")
    def bomb(self) -> bytes:
        """380KB on the wire, ~194MB unpacked — under every size limit."""
        return make_docx(paragraph(b"A" * 2000) * 100_000)

    def test_the_bomb_really_does_look_legitimate(self, bomb):
        assert len(bomb) < 1024 * 1024
        assert bomb.startswith(b"PK\x03\x04")
        with zipfile.ZipFile(io.BytesIO(bomb)) as archive:
            declared = sum(i.file_size for i in archive.infolist())
        assert declared > 150 * 1024 * 1024

    def test_it_is_refused_before_anything_is_decompressed(self, bomb):
        with pytest.raises(UnsupportedFileType) as err:
            extract_text(bomb, DOCX_MIME, "cv.docx")
        assert "unpacks to" in str(err.value)
        assert str(MAX_DOCX_UNCOMPRESSED_MB) in str(err.value)

    def test_refusing_it_costs_no_memory(self, bomb):
        """The whole point: the check reads the archive directory, not the
        entries."""
        import resource

        before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        with pytest.raises(UnsupportedFileType):
            extract_text(bomb, DOCX_MIME, "cv.docx")
        after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        assert (after - before) < 50 * 1024, f"grew {(after - before) / 1024:.0f}MB"

    def test_a_file_just_under_the_cap_is_still_accepted(self):
        under = make_docx(paragraph(b"A" * 2000) * 5_000)  # ~10MB unpacked
        check_docx_expansion(under)  # must not raise


class TestBrokenFiles:
    def test_an_empty_file_is_rejected(self):
        with pytest.raises((ParseError, UnsupportedFileType)):
            extract_text(b"", DOCX_MIME, "cv.docx")

    def test_something_that_is_not_a_zip_is_rejected(self):
        with pytest.raises(UnsupportedFileType):
            extract_text(b"<html>not a docx</html>", DOCX_MIME, "cv.docx")

    def test_a_truncated_archive_is_reported_as_corrupted(self):
        broken = make_docx(paragraph(CV_TEXT))[:120]
        with pytest.raises(UnsupportedFileType) as err:
            extract_text(broken, DOCX_MIME, "cv.docx")
        assert "corrupted" in str(err.value).lower()

    def test_a_zip_that_is_not_a_docx_is_reported_readably(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("notes.txt", "hello")

        with pytest.raises(ParseError) as err:
            extract_text(buf.getvalue(), DOCX_MIME, "cv.docx")
        message = str(err.value)
        # The library's own message ("'lxml.etree._Element' object has no
        # attribute 'overrides'") told a recruiter nothing and exposed what
        # we run.
        assert "lxml" not in message
        assert "object has no attribute" not in message
        assert "re-saving" in message

    def test_a_docx_with_no_readable_text_says_so(self):
        with pytest.raises(ParseError) as err:
            extract_text(make_docx(paragraph(b"hi")), DOCX_MIME, "cv.docx")
        assert "could not extract text" in str(err.value).lower()

    def test_an_unsupported_format_is_named(self):
        with pytest.raises(UnsupportedFileType):
            extract_text(b"PK\x03\x04 whatever", "image/png", "photo.png")


class TestPdf:
    def test_a_pdf_without_a_pdf_header_is_refused(self):
        with pytest.raises(UnsupportedFileType) as err:
            extract_text(b"not a pdf at all, just some bytes", "application/pdf", "cv.pdf")
        assert "%PDF" in str(err.value)

    def test_an_unreadable_pdf_gives_the_scanned_document_advice(self):
        with pytest.raises(ParseError) as err:
            extract_text(b"%PDF-1.4\n" + b"\x00" * 4000, "application/pdf", "cv.pdf")
        assert "scanned" in str(err.value).lower()
