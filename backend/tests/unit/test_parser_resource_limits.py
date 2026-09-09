"""
HireLens — document parsing resource limits
Run: cd backend && python -m pytest tests/unit/test_parser_resource_limits.py -v

The upload size cap only limits the COMPRESSED bytes that arrive. What
happens after that had no ceiling at all:

  ZIP BOMB — a DOCX is a ZIP archive, and highly repetitive XML compresses at
  ratios in the thousands. A 10MB upload that passes every existing check can
  expand to gigabytes the instant python-docx reads word/document.xml, which
  OOM-kills a single-worker container.

  EVENT-LOOP BLOCKING — extract_text() is synchronous and CPU-bound, and was
  called directly from an async background task. One pathological document
  froze the entire API for its duration: not just that job, every other
  recruiter's requests too. ANALYSIS_TIMEOUT_SECONDS never covered this; it
  only wraps the LLM call inside engine.run().

  LEAKED INTERNALS — parse failures returned str(exception) to the client
  through the job status, exposing library internals and paths.
"""

import io
import zipfile

import pytest

from app.services.parser import document_parser
from app.services.parser.document_parser import extract_text
from app.core.exceptions import UnsupportedFileType, ParseError


def _zip_with(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in entries.items():
            z.writestr(name, content)
    return buf.getvalue()


class TestZipBombGuard:
    def test_a_highly_compressible_payload_is_rejected(self):
        """The actual attack: tiny upload, enormous expansion."""
        bomb = _zip_with({"word/document.xml": b"A" * (60 * 1024 * 1024)})

        # It really is small enough to sail past the upload cap.
        assert len(bomb) < 1 * 1024 * 1024

        with pytest.raises(UnsupportedFileType):
            extract_text(
                bomb,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "bomb.docx",
            )

    def test_the_check_reads_the_directory_and_does_not_decompress(self):
        """Decompressing in order to decide whether to decompress would be
        the same bug wearing a hat."""
        bomb = _zip_with({"word/document.xml": b"B" * (200 * 1024 * 1024)})

        with pytest.raises(UnsupportedFileType):
            document_parser._reject_zip_bomb(bomb)

    def test_an_absurd_ratio_is_rejected_even_when_small(self):
        content = b"C" * (document_parser.MAX_DOCX_COMPRESSION_RATIO * 4096)
        with pytest.raises(UnsupportedFileType):
            document_parser._reject_zip_bomb(_zip_with({"word/document.xml": content}))

    def test_an_ordinary_docx_sized_archive_passes(self):
        """Don't over-correct: a normal resume must not be rejected.

        Stored (uncompressed) so the ratio stays near 1, which is what a
        real document with images and fonts looks like.
        """
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
            z.writestr("word/document.xml", b"<w:document>" + b"x" * 20_000 + b"</w:document>")
        document_parser._reject_zip_bomb(buf.getvalue())  # must not raise

    def test_a_corrupted_archive_gets_a_readable_error(self):
        with pytest.raises(UnsupportedFileType) as exc:
            document_parser._reject_zip_bomb(b"PK\x03\x04 this is not really a zip")
        assert "corrupted" in exc.value.message.lower()


class TestParseErrorsAreUserFacing:
    def test_a_broken_docx_does_not_leak_the_underlying_exception(self):
        """This message is returned to the client through the job status."""
        # A structurally valid ZIP that is not a DOCX: python-docx will fail
        # somewhere in its own internals.
        not_a_docx = _zip_with({"hello.txt": b"just a text file"})

        with pytest.raises(ParseError) as exc:
            extract_text(
                not_a_docx,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "fake.docx",
            )

        message = exc.value.message
        assert "Traceback" not in message
        assert "/home/" not in message
        assert "docx" in message.lower()
        # ...and it tells the user what to actually do.
        assert "PDF" in message or "re-sav" in message

    def test_a_pdf_without_extractable_text_explains_why(self):
        minimal_pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
        with pytest.raises(ParseError) as exc:
            extract_text(minimal_pdf, "application/pdf", "scan.pdf")
        assert "scanned" in exc.value.message.lower()


class TestParsingIsOffTheEventLoop:
    """The blocking call is what made one bad document everyone's problem."""

    def test_run_analysis_parses_in_a_thread_with_a_timeout(self):
        import inspect
        from app.api.v1.endpoints import analysis

        src = inspect.getsource(analysis._run_analysis)

        assert "asyncio.to_thread(extract_text" in src, (
            "extract_text is synchronous and CPU-bound; calling it directly "
            "from the async task blocks the whole event loop"
        )
        assert "PARSE_TIMEOUT_SECONDS" in src, "parsing needs its own ceiling"

    def test_parse_timeout_is_configured_and_bounded(self):
        from app.core.config import settings

        assert settings.PARSE_TIMEOUT_SECONDS > 0
        # Long enough for a dense multi-page PDF, short enough that a stuck
        # parse does not tie up a thread for minutes.
        assert 10 <= settings.PARSE_TIMEOUT_SECONDS <= 120
