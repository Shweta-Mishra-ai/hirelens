"""
HireLens — information-disclosure tests
Run: cd backend && python -m pytest tests/unit/test_information_disclosure.py -v

Three separate leaks, all of the same shape: something the app knows escaping
to somewhere it shouldn't.

1. EXISTENCE ORACLES. Answering 403 for "this exists but isn't yours" and 404
   for "no such thing" lets a caller confirm whether an id they hold is real
   without ever being able to read it. The reports router already answered 404
   for both (test_nonexistent_report_raises_not_found_not_forbidden); the
   collaboration router and the job-status endpoint did not.

2. PROVIDER SECRETS IN LOGS. Only the Gemini key was redacted from LLM error
   text. SDKs and HTTP layers routinely echo the failing request — including
   its Authorization header — into the exception, and that string went
   straight into the application log.

3. CANDIDATE EMAILS IN LOGS. Candidates are not users. They never signed up
   here and cannot ask for their data back, yet their address was written at
   INFO on every notification. Logs outlive reports, get shipped to third
   parties, and are readable by people who were never given access to the
   report itself.
"""

import inspect

import pytest

from app.core.redaction import mask_email
from app.core.exceptions import NotFoundError


class TestExistenceOracles:
    def test_job_status_answers_404_for_someone_elses_job(self):
        import asyncio
        from app.api.v1.endpoints.analysis import _jobs, get_status

        _jobs["job-oracle-1"] = {
            "id": "job-oracle-1",
            "user_id": "owner-user",
            "status": "complete",
            "stage": "done",
            "progress": 100,
            "file_name": "cv.pdf",
            "report_id": "rep-1",
            "error": None,
        }
        try:
            with pytest.raises(NotFoundError):
                asyncio.run(
                    get_status("job-oracle-1", current_user={"id": "other-user"})
                )
            # ...and the same answer for an id that simply doesn't exist, so
            # the two cases are indistinguishable from outside.
            with pytest.raises(NotFoundError):
                asyncio.run(get_status("no-such-job", current_user={"id": "other-user"}))
        finally:
            _jobs.pop("job-oracle-1", None)

    def test_collaboration_router_never_answers_403(self):
        """Every access failure in this router must be 404.

        Asserted against the source rather than by driving each of the eight
        endpoints with a live DB, because the property being protected is
        "no code path in this file raises Forbidden" — a new endpoint added
        later with a 403 is exactly what should fail this.
        """
        from app.api.v1.endpoints import collaboration

        src = inspect.getsource(collaboration)
        assert "ForbiddenError" not in src, (
            "A 403 in the collaboration router confirms a report id exists but "
            "belongs to someone else. Use _report_not_found() instead."
        )

    def test_report_not_found_message_does_not_distinguish_the_two_cases(self):
        from app.api.v1.endpoints.collaboration import _report_not_found

        err = _report_not_found("abc-123")
        assert err.http_status == 404
        # The message must not say "forbidden", "access", "owner" or anything
        # else that re-adds the distinction the status code just removed.
        lowered = err.message.lower()
        for leak in ("forbid", "permission", "access", "owner", "not yours"):
            assert leak not in lowered


class TestSecretRedaction:
    def test_every_provider_key_is_redacted_not_just_gemini(self, monkeypatch):
        from app.core.config import settings
        from app.services.ai import engine

        monkeypatch.setattr(settings, "GEMINI_API_KEY", "gem-secret-aaa")
        monkeypatch.setattr(settings, "GROQ_API_KEY", "groq-secret-bbb")
        monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "anthropic-secret-ccc")

        raw = (
            "401 Unauthorized for url https://api.groq.com/v1/chat "
            "headers={'Authorization': 'Bearer groq-secret-bbb'} "
            "fallback key gem-secret-aaa and anthropic-secret-ccc"
        )
        cleaned = engine._redact_secrets(raw)

        assert "groq-secret-bbb" not in cleaned
        assert "gem-secret-aaa" not in cleaned
        assert "anthropic-secret-ccc" not in cleaned
        assert "REDACTED" in cleaned
        # The rest of the message must survive — a redactor that eats the
        # error is useless for debugging.
        assert "401 Unauthorized" in cleaned

    def test_redaction_is_a_no_op_when_no_keys_are_configured(self, monkeypatch):
        from app.core.config import settings
        from app.services.ai import engine

        monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
        monkeypatch.setattr(settings, "GROQ_API_KEY", "")
        monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")

        assert engine._redact_secrets("plain error text") == "plain error text"

    def test_llm_error_paths_route_through_the_redactor(self):
        """Both the LLMError and the generic-exception branch log provider
        text; neither may bypass redaction."""
        from app.services.ai import engine

        src = inspect.getsource(engine.llm_call)
        for line in src.splitlines():
            if "logger.warning" in line and "provider_name" in line:
                assert "_redact_secrets" in line or "attempt" not in line, line


class TestCandidateEmailMasking:
    def test_mask_keeps_the_domain_and_drops_the_identity(self):
        assert mask_email("jane.doe@example.com") == "j***@example.com"

    def test_handles_missing_and_malformed_values_without_raising(self):
        # These run inside a logging call on a notification path; throwing
        # here would turn a redaction helper into an outage.
        assert mask_email(None) == "<none>"
        assert mask_email("") == "<none>"
        assert mask_email("not-an-email") == "<invalid>"
        assert mask_email("@example.com") == "<blank>@example.com"

    def test_notify_log_line_does_not_contain_the_raw_address(self):
        from app.api.v1.endpoints import reports

        src = inspect.getsource(reports.notify_candidate)
        assert "mask_email(candidate_email)" in src
        assert "to={candidate_email}" not in src

    def test_email_sender_masks_recipients(self):
        from app.services.email import sender

        src = inspect.getsource(sender)
        # Every INFO line naming a recipient goes through the masker.
        for line in src.splitlines():
            if "logger.info" in line and "to_email" in line:
                assert "mask_email(to_email)" in line, line
