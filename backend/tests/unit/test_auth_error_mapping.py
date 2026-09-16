"""
HireLens — What the app tells someone when auth fails

Every message here is one a real person reads at the moment they cannot get
into their account. The rule the whole module turns on: a decision by the
identity provider is an answer and must stand; an unreachable provider is not
an answer and must not be reported as one.

Run: cd backend && python -m pytest tests/unit/test_auth_error_mapping.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest

from app.core.exceptions import (
    AuthError,
    ConflictError,
    RateLimitExceeded,
    ValidationError,
)
from app.services.auth.errors import classify
from supabase_auth.errors import (
    AuthApiError,
    AuthRetryableError,
    AuthWeakPasswordError,
)


class TestRateLimitIsNotAWrongPassword:
    def test_a_429_is_reported_as_too_many_attempts(self):
        """
        The one that matters most. A 429 sits inside 4xx, so any rule that
        treats "the provider answered with 4xx" as "the credentials are wrong"
        tells someone their correct password is wrong — and sends them off to
        reset a password that was never the problem.
        """
        kind, error = classify(
            AuthApiError("Request rate limit reached", 429, "over_request_rate_limit"),
            action="login",
        )
        assert kind == "rejected"
        assert isinstance(error, RateLimitExceeded)
        assert "password" not in error.message.lower()
        assert "too many" in error.message.lower()

    def test_an_email_send_limit_says_so_and_asks_for_patience(self):
        kind, error = classify(
            AuthApiError("email rate limit exceeded", 429, "over_email_send_rate_limit"),
            action="reset",
        )
        assert isinstance(error, RateLimitExceeded)
        assert error.retry_after == 900
        assert "email" in error.message.lower()


class TestPasswordPolicy:
    def test_a_breached_password_is_named_as_such(self):
        """Leaked-password protection rejects passwords that look strong. Told
        to "choose something stronger", a user reasonably tries a longer
        variant of the same breached password and is refused again."""
        kind, error = classify(
            AuthApiError(
                "Password is known to be weak and easy to guess, please choose a different one.",
                422,
                "weak_password",
            ),
            action="signup",
        )
        assert kind == "rejected"
        assert isinstance(error, ValidationError)
        assert "data breach" in error.message.lower()

    def test_a_policy_failure_names_the_rules_it_broke(self):
        kind, error = classify(
            AuthWeakPasswordError(
                "Password should contain at least one character of each",
                422,
                ["length", "symbols"],
            ),
            action="signup",
        )
        assert isinstance(error, ValidationError)
        assert "length" in error.message and "symbols" in error.message

    def test_reusing_the_current_password_is_explained(self):
        _, error = classify(
            AuthApiError("New password should be different from the old password.", 422, "same_password"),
            action="reset",
        )
        assert isinstance(error, ValidationError)
        assert "different" in error.message.lower()


class TestAccountState:
    def test_a_taken_address_is_a_conflict_not_an_outage(self):
        kind, error = classify(
            AuthApiError("User already registered", 422, "email_exists"), action="signup"
        )
        assert kind == "rejected"
        assert isinstance(error, ConflictError)
        assert error.http_status == 409

    def test_an_unconfirmed_email_tells_them_where_to_look(self):
        _, error = classify(
            AuthApiError("Email not confirmed", 400, "email_not_confirmed"), action="login"
        )
        assert isinstance(error, AuthError)
        assert "confirm" in error.message.lower()
        assert "inbox" in error.message.lower()

    def test_an_invalid_address_is_a_validation_error(self):
        _, error = classify(
            AuthApiError("Unable to validate email address", 400, "email_address_invalid"),
            action="signup",
        )
        assert isinstance(error, ValidationError)


class TestResetLinks:
    @pytest.mark.parametrize(
        "code",
        ["otp_expired", "bad_jwt", "session_expired", "session_not_found"],
    )
    def test_a_spent_or_expired_link_says_to_ask_for_another(self, code):
        _, error = classify(AuthApiError("Email link is invalid or has expired", 401, code), action="reset")
        assert isinstance(error, AuthError)
        assert "expired" in error.message.lower() or "already been used" in error.message.lower()
        assert "new one" in error.message.lower()


class TestCredentials:
    def test_wrong_credentials_stay_vague_on_login(self):
        """Deliberately identical whether the account exists or not — a
        different message for an unknown address turns sign-in into a way to
        find out who has an account."""
        _, error = classify(
            AuthApiError("Invalid login credentials", 400, "invalid_credentials"), action="login"
        )
        assert error.message == "Invalid email or password."

    def test_an_unknown_user_on_reset_reveals_nothing(self):
        _, error = classify(
            AuthApiError("User not found", 404, "user_not_found"), action="reset"
        )
        assert "not found" not in error.message.lower()
        assert "no account" not in error.message.lower()


class TestUnreachableProviderIsNotADecision:
    def test_a_retryable_error_is_unavailable(self):
        kind, error = classify(AuthRetryableError("connection failed", 0), action="login")
        assert kind == "unavailable"
        assert error is None

    def test_a_500_is_unavailable(self):
        kind, error = classify(AuthApiError("internal error", 500, None), action="login")
        assert kind == "unavailable"
        assert error is None

    def test_a_plain_exception_from_our_own_code_is_unavailable(self):
        kind, error = classify(TypeError("something in our code"), action="login")
        assert kind == "unavailable"
        assert error is None


class TestUnmappedRejectionsStillStand:
    def test_an_unknown_4xx_on_login_is_still_a_rejection(self):
        """A 4xx we have no wording for is still a decision. Reporting it as an
        outage would tell the user to try again later, when trying again will
        fail in exactly the same way."""
        kind, error = classify(AuthApiError("some new error", 400, "brand_new_code"), action="login")
        assert kind == "rejected"
        assert isinstance(error, AuthError)

    def test_an_unknown_4xx_on_signup_asks_them_to_check_their_details(self):
        kind, error = classify(AuthApiError("some new error", 400, "brand_new_code"), action="signup")
        assert kind == "rejected"
        assert isinstance(error, ValidationError)
