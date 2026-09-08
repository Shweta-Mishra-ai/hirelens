"""
HireLens — abuse / resource-exhaustion limit tests
Run: cd backend && python -m pytest tests/unit/test_abuse_limits.py -v

Signup is open, so "requires authentication" is not a barrier — anyone
willing to register gets whatever an authenticated caller can do. These
endpoints each hand an authenticated caller something expensive, and each had
no limit on it:

  POST /verify/{id}/run   — fans out to four concurrent outbound HTTP checks
                            per call (GitHub API, a domain registry, a live
                            fetch of every certification link in the resume,
                            an employer-domain probe). Looping it saturates a
                            single-worker container, burns the GitHub quota
                            every user shares, and turns the server into an
                            outbound request amplifier aimed at whatever URLs
                            a candidate put in their resume.

  POST /teams/{id}/invite — sends email to an address in the request body.
                            The only guard was a duplicate check for the same
                            address on the same team, which is bypassed by
                            changing the address. Unlimited mail out of the
                            configured Resend account: spam delivered in
                            HireLens's name, and a sending domain that gets
                            blacklisted.

  POST /reports/{id}/comments — unbounded 2000-char writes into the DB and
                            every teammate's thread.

The limits are deliberately generous — they should be invisible to a person
and fatal to a loop.
"""

import pytest

from app.core.exceptions import RateLimitExceeded
from app.core.rate_limit import check_rate_limit, _mem_rate_limit
from app.api.v1.endpoints.verify import VERIFY_RUNS_PER_MINUTE, VERIFY_RUNS_PER_HOUR
from app.api.v1.endpoints.teams import INVITES_PER_HOUR, INVITES_PER_DAY
from app.api.v1.endpoints.collaboration import COMMENTS_PER_MINUTE


@pytest.fixture(autouse=True)
def clean_limiter():
    _mem_rate_limit.clear()
    yield
    _mem_rate_limit.clear()


def _exhaust(key: str, limit: int, window: int = 60):
    """Spend the whole budget, then assert the next call is refused."""
    for _ in range(limit):
        check_rate_limit(None, key, limit, window_seconds=window)
    with pytest.raises(RateLimitExceeded):
        check_rate_limit(None, key, limit, window_seconds=window)


class TestVerifyRunLimit:
    def test_per_minute_budget_is_enforced(self):
        _exhaust("verify-run:user-1", VERIFY_RUNS_PER_MINUTE, 60)

    def test_per_hour_budget_is_enforced(self):
        """A slow drip that stays under the per-minute cap must still stop."""
        _exhaust("verify-run-hr:user-1", VERIFY_RUNS_PER_HOUR, 3600)

    def test_limits_are_per_user_not_global(self):
        """One noisy account must not lock everyone else out of verification."""
        for _ in range(VERIFY_RUNS_PER_MINUTE):
            check_rate_limit(None, "verify-run:noisy", VERIFY_RUNS_PER_MINUTE, 60)
        with pytest.raises(RateLimitExceeded):
            check_rate_limit(None, "verify-run:noisy", VERIFY_RUNS_PER_MINUTE, 60)

        # A different recruiter is unaffected.
        check_rate_limit(None, "verify-run:someone-else", VERIFY_RUNS_PER_MINUTE, 60)

    def test_budget_is_small_enough_to_matter(self):
        """A limit set high enough to be decorative is not a limit.

        Each run costs four outbound HTTP calls, so the per-hour ceiling is
        also a ceiling on outbound requests this endpoint can generate for one
        account. Pin it so nobody "temporarily" raises it into uselessness.
        """
        assert VERIFY_RUNS_PER_MINUTE <= 30
        assert VERIFY_RUNS_PER_HOUR <= 200
        assert VERIFY_RUNS_PER_HOUR * 4 <= 1000


class TestInviteLimit:
    def test_per_hour_budget_is_enforced(self):
        _exhaust("team-invite:user-1", INVITES_PER_HOUR, 3600)

    def test_per_day_budget_is_enforced(self):
        _exhaust("team-invite-day:user-1", INVITES_PER_DAY, 86400)

    def test_key_is_per_user_so_extra_teams_buy_no_extra_sending(self):
        """Keying on team id would make the limit free to bypass: create a new
        team, get a fresh budget. The key must be the account."""
        import inspect
        from app.api.v1.endpoints import teams

        src = inspect.getsource(teams.invite_member)
        assert 'f"team-invite:{current_user[\'id\']}"' in src
        assert "team_id" not in src.split("check_rate_limit")[1].split(")")[0]

    def test_daily_ceiling_is_a_real_ceiling(self):
        assert INVITES_PER_HOUR <= 50
        assert INVITES_PER_DAY <= 200


class TestCommentLimit:
    def test_per_minute_budget_is_enforced(self):
        _exhaust("comment:user-1", COMMENTS_PER_MINUTE, 60)

    def test_budget_allows_a_real_conversation(self):
        """Don't over-correct: a person in a fast discussion must not hit it."""
        assert COMMENTS_PER_MINUTE >= 10
