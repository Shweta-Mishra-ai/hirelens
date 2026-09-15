"""
Tests for recruiter-facing failure copy.

Raw exception text used to be passed straight through to the UI, producing
messages like "Could not read file: No /Root object! - Is this really a PDF?"
and provider errors naming GEMINI_API_KEY and .env paths.
"""

import pytest

from app.api.v1.endpoints.analysis import (
    _analysis_failure_message,
    _parse_failure_message,
)


class TestParseFailures:
    def test_scanned_document_gets_specific_guidance(self):
        msg = _parse_failure_message(
            "cv.pdf",
            Exception("Could not extract text from this PDF. Ensure it's a text-selectable PDF (not scanned)."),
        )
        assert "scan" in msg.lower()
        assert "OCR" in msg or "original" in msg

    def test_encrypted_document(self):
        msg = _parse_failure_message("cv.pdf", Exception("File has not been decrypted; password required"))
        assert "password" in msg.lower()
        assert "unprotected" in msg.lower()

    def test_corrupt_pdf_names_the_format_not_the_internals(self):
        msg = _parse_failure_message("cv.pdf", Exception("No /Root object! - Is this really a PDF?"))
        assert "/Root" not in msg
        assert "PDF" in msg
        assert "corrupt" in msg.lower() or "re-export" in msg.lower()

    def test_unknown_error_still_gives_a_next_step(self):
        msg = _parse_failure_message("cv.docx", Exception("some internal parser explosion"))
        assert "internal parser explosion" not in msg
        assert "PDF or DOCX" in msg

    @pytest.mark.parametrize(
        "err",
        [
            Exception("No /Root object!"),
            Exception("password required"),
            Exception(""),
            Exception("a" * 5000),
        ],
    )
    def test_never_raises_and_never_returns_empty(self, err):
        msg = _parse_failure_message("cv.pdf", err)
        assert isinstance(msg, str) and msg.strip()


class TestAnalysisFailures:
    def test_rate_limit_tells_the_user_to_retry(self):
        msg = _analysis_failure_message(Exception("Gemini rate limit hit. Try again in a moment."))
        assert "rate-limit" in msg.lower() or "rate limit" in msg.lower()
        assert "try again" in msg.lower()

    def test_timeout_is_explained(self):
        msg = _analysis_failure_message(Exception("Analysis timed out after 120s"))
        assert "longer than expected" in msg.lower()

    def test_missing_key_does_not_leak_operator_advice(self):
        msg = _analysis_failure_message(
            Exception("No LLM API key configured. Set GEMINI_API_KEY (free at aistudio.google.com) in your .env file.")
        )
        assert "GEMINI_API_KEY" not in msg
        assert ".env" not in msg
        assert "aistudio" not in msg
        assert "administrator" in msg.lower()

    def test_safety_block_is_explained_without_accusation(self):
        msg = _analysis_failure_message(Exception("Gemini blocked the request: SAFETY"))
        assert "declined" in msg.lower()
        # Must not imply the candidate did something wrong.
        assert "fraud" not in msg.lower()

    def test_unknown_failure_is_generic_but_useful(self):
        msg = _analysis_failure_message(Exception("segfault in provider sdk 0xdeadbeef"))
        assert "0xdeadbeef" not in msg
        assert "try again" in msg.lower()

    def test_never_echoes_an_api_key_shaped_string(self):
        msg = _analysis_failure_message(Exception("auth failed for key AIzaSyC-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"))
        assert "AIzaSy" not in msg
