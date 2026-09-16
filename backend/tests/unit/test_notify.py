"""
HireLens — Candidate Decision Notification Unit Tests
Run: cd backend && python -m pytest tests/unit/test_notify.py -v

Covers:
- build_decision_email(): correct template selection + placeholder filling
- send_raw_email(): provider fallback order (Resend -> SMTP -> no-op), and
  that a failed/misconfigured provider never raises (silent-fail-safe,
  the caller decides how to report it to the user).
"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app.services.email.sender import build_decision_email, send_raw_email
from app.core.config import settings


class TestBuildDecisionEmail:
    def test_advance_template_fills_all_placeholders(self):
        draft = build_decision_email("advance", "Priya Sharma", "Alex Recruiter", "Acme Corp")
        assert "Priya Sharma" in draft["body"]
        assert "Alex Recruiter" in draft["body"]
        assert "Acme Corp" in draft["subject"]
        assert "move forward" in draft["body"].lower()

    def test_reject_template_is_polite_and_generic(self):
        draft = build_decision_email("reject", "Arjun Mehta", "Alex Recruiter", "Acme Corp")
        assert "Arjun Mehta" in draft["body"]
        # Must NOT contain internal AI reasoning/flag language — this is a
        # deliberate product decision (see conversation), not an oversight.
        assert "flag" not in draft["body"].lower()
        assert "score" not in draft["body"].lower()
        assert "credibility" not in draft["body"].lower()

    def test_schedule_followup_template_exists_and_differs_from_others(self):
        followup = build_decision_email("schedule_followup", "Sam Lee", "Alex", "Acme")
        advance = build_decision_email("advance", "Sam Lee", "Alex", "Acme")
        reject = build_decision_email("reject", "Sam Lee", "Alex", "Acme")
        assert followup["body"] != advance["body"]
        assert followup["body"] != reject["body"]

    def test_missing_candidate_name_falls_back_to_generic_greeting(self):
        draft = build_decision_email("advance", "", "Alex", "Acme")
        assert "Hi there" in draft["body"]

    def test_missing_sender_name_falls_back_to_generic_signoff(self):
        draft = build_decision_email("advance", "Sam", "", "Acme")
        assert "The Hiring Team" in draft["body"]

    def test_unknown_decision_falls_back_to_reject_template(self):
        draft = build_decision_email("not_a_real_decision", "Sam", "Alex", "Acme")
        reject = build_decision_email("reject", "Sam", "Alex", "Acme")
        assert draft["body"] == reject["body"]

    def test_all_three_decisions_produce_distinct_subjects_or_bodies(self):
        d1 = build_decision_email("advance", "Sam", "Alex", "Acme")
        d2 = build_decision_email("schedule_followup", "Sam", "Alex", "Acme")
        d3 = build_decision_email("reject", "Sam", "Alex", "Acme")
        bodies = {d1["body"], d2["body"], d3["body"]}
        assert len(bodies) == 3


class TestSendRawEmailFallback:
    """
    These tests temporarily override module-level settings to exercise
    the provider-selection branches without making real network calls.
    httpx/smtplib calls are expected to fail fast against bogus
    hosts/keys — we only assert that failure is swallowed, not raised,
    and that the function returns False rather than crashing the caller.
    """

    def setup_method(self):
        self._orig_resend = settings.RESEND_API_KEY
        self._orig_smtp_host = settings.SMTP_HOST
        self._orig_smtp_user = settings.SMTP_USER
        self._orig_smtp_pass = settings.SMTP_PASSWORD

    def teardown_method(self):
        settings.RESEND_API_KEY = self._orig_resend
        settings.SMTP_HOST = self._orig_smtp_host
        settings.SMTP_USER = self._orig_smtp_user
        settings.SMTP_PASSWORD = self._orig_smtp_pass

    def test_no_provider_configured_returns_false_without_raising(self):
        settings.RESEND_API_KEY = ""
        settings.SMTP_HOST = ""
        settings.SMTP_USER = ""
        settings.SMTP_PASSWORD = ""
        result = asyncio.run(send_raw_email("candidate@example.com", "Subject", "<p>hi</p>", "hi"))
        assert result is False

    def _with_resend(self, monkeypatch, handler):
        """Point the sender's httpx client at a scripted transport.

        This used to make a real HTTPS request to api.resend.com with a bogus
        key, which made the test depend on the network and — worse — sent a
        candidate's email address to a third party from every test run.
        """
        import httpx

        real = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)
        settings.RESEND_API_KEY = "test-key"
        settings.SMTP_HOST = ""

    def test_a_rejected_resend_key_returns_false_without_raising(self, monkeypatch):
        import httpx

        self._with_resend(monkeypatch, lambda r: httpx.Response(401, text="invalid api key"))
        result = asyncio.run(send_raw_email("candidate@example.com", "Subject", "<p>hi</p>", "hi"))
        assert result is False

    def test_a_resend_outage_returns_false_without_raising(self, monkeypatch):
        import httpx

        def boom(request):
            raise httpx.ConnectError("no route to host", request=request)

        self._with_resend(monkeypatch, boom)
        result = asyncio.run(send_raw_email("candidate@example.com", "Subject", "<p>hi</p>", "hi"))
        assert result is False

    def test_a_delivered_email_returns_true(self, monkeypatch):
        """Nothing covered the success path, so a change that stopped mail
        going out would not have failed a single test."""
        import httpx

        sent = {}

        def handler(request):
            import json as _json

            sent.update(_json.loads(request.content))
            sent["auth"] = request.headers.get("Authorization")
            return httpx.Response(200, json={"id": "email-1"})

        self._with_resend(monkeypatch, handler)
        result = asyncio.run(
            send_raw_email("candidate@example.com", "Interview invite", "<p>hi</p>", "hi")
        )
        assert result is True
        assert sent["to"] == ["candidate@example.com"]
        assert sent["subject"] == "Interview invite"
        assert sent["html"] == "<p>hi</p>"
        assert sent["auth"] == "Bearer test-key"

    def test_bad_smtp_host_falls_through_without_raising(self):
        # `.test` is reserved by RFC 6761 and never resolves, so this fails
        # at DNS without leaving the machine.
        settings.RESEND_API_KEY = ""
        settings.SMTP_HOST = "smtp.invalid-host-that-does-not-exist.test"
        settings.SMTP_USER = "user"
        settings.SMTP_PASSWORD = "pass"
        result = asyncio.run(send_raw_email("candidate@example.com", "Subject", "<p>hi</p>", "hi"))
        assert result is False


class TestNotifyEndpointRateLimiting:
    """
    The single-report /notify and batch /notify-all endpoints trigger real
    outbound emails, so they carry their own (tighter) rate limit rather
    than relying on the general per-endpoint limits. These tests exercise
    the shared check_rate_limit() helper directly against the notify-specific
    settings value, the same way the endpoints call it.
    """

    def test_notify_rate_limit_allows_up_to_configured_limit(self):
        from app.core.rate_limit import check_rate_limit, _mem_rate_limit
        from app.core.config import settings

        key = "test-notify-user-allows"
        _mem_rate_limit.pop(key, None)  # isolate from any prior test run
        for _ in range(settings.NOTIFY_RATE_LIMIT_PER_MINUTE):
            check_rate_limit(None, key, settings.NOTIFY_RATE_LIMIT_PER_MINUTE)  # should not raise
        _mem_rate_limit.pop(key, None)

    def test_notify_rate_limit_blocks_after_configured_limit(self):
        from app.core.rate_limit import check_rate_limit, _mem_rate_limit
        from app.core.config import settings
        from app.core.exceptions import RateLimitExceeded

        key = "test-notify-user-blocks"
        _mem_rate_limit.pop(key, None)
        for _ in range(settings.NOTIFY_RATE_LIMIT_PER_MINUTE):
            check_rate_limit(None, key, settings.NOTIFY_RATE_LIMIT_PER_MINUTE)
        try:
            check_rate_limit(None, key, settings.NOTIFY_RATE_LIMIT_PER_MINUTE)
            assert False, "expected RateLimitExceeded on the (limit+1)th call"
        except RateLimitExceeded as e:
            assert e.http_status == 429
        _mem_rate_limit.pop(key, None)

    def test_different_users_have_independent_notify_limits(self):
        from app.core.rate_limit import check_rate_limit, _mem_rate_limit
        from app.core.config import settings

        key_a, key_b = "test-notify-user-a", "test-notify-user-b"
        _mem_rate_limit.pop(key_a, None)
        _mem_rate_limit.pop(key_b, None)
        for _ in range(settings.NOTIFY_RATE_LIMIT_PER_MINUTE):
            check_rate_limit(None, key_a, settings.NOTIFY_RATE_LIMIT_PER_MINUTE)
        # User B's identical action must not be affected by user A's usage.
        check_rate_limit(None, key_b, settings.NOTIFY_RATE_LIMIT_PER_MINUTE)  # should not raise
        _mem_rate_limit.pop(key_a, None)
        _mem_rate_limit.pop(key_b, None)
