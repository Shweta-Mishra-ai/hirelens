"""
HireLens — Invites match the person who was invited

Invites are matched by email address at sign-up. Both halves of that match
have to agree on how an address is written, and when they don't the failure is
silent: the invitee signs up, joins no team, and neither they nor the person
who invited them sees an error.

Run: cd backend && python -m pytest tests/unit/test_invite_matching.py -v
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest

from tests.fake_supabase import FakeSupabase
from app.services.teams.access import (
    accept_pending_invites_for_email, normalize_email,
    _mem_team_invites, _mem_team_members, _mem_teams,
)
from app.api.v1.endpoints.teams import invite_member, _invite_url, InviteRequest


@pytest.fixture(autouse=True)
def clean_stores():
    """Both stores, because invite_member deliberately writes to each: the
    durable local row is what lets an invite survive a restart, and a leftover
    row from the previous test would otherwise be counted by the next one."""
    from app.core import local_db

    def _reset():
        for store in (_mem_team_invites, _mem_team_members):
            store[:] = []
        _mem_teams.clear()
        with local_db._get_connection() as conn:
            conn.execute("DELETE FROM team_invites")
            conn.execute("DELETE FROM team_members")
            conn.commit()

    _reset()
    yield
    _reset()


class TestNormalizeEmail:
    def test_lowercases_and_trims(self):
        assert normalize_email("  Shweta.M@GMAIL.com ") == "shweta.m@gmail.com"

    def test_already_normal_is_unchanged(self):
        assert normalize_email("a@b.com") == "a@b.com"

    def test_none_and_empty_are_safe(self):
        assert normalize_email(None) == ""
        assert normalize_email("") == ""


class TestInvitesAreStoredNormalized:
    """The write side. An invite row written in the inviter's own casing can
    never be matched: sign-up lowercases the address before it looks."""

    def _invite(self, db, address):
        return asyncio.run(invite_member(
            team_id="team-1",
            body=InviteRequest(email=address),
            current_user={"id": "owner-1", "email": "owner@example.com"},
            db=db,
        ))

    def _db(self):
        return FakeSupabase(tables={
            "teams": [{"id": "team-1", "name": "Hiring", "owner_id": "owner-1"}],
            "team_members": [{"team_id": "team-1", "user_id": "owner-1", "role": "owner"}],
            "team_invites": [],
        })

    def test_supabase_row_is_lowercased(self):
        db = self._db()
        self._invite(db, "Shweta.M@Gmail.com")
        assert db.tables["team_invites"][0]["email"] == "shweta.m@gmail.com"

    def test_response_reports_the_stored_address(self):
        db = self._db()
        result = self._invite(db, "Shweta.M@Gmail.com")
        assert result["email"] == "shweta.m@gmail.com"

    def test_in_process_cache_is_lowercased_too(self):
        db = self._db()
        self._invite(db, "Shweta.M@Gmail.com")
        assert _mem_team_invites[-1]["email"] == "shweta.m@gmail.com"

    def test_reinviting_the_same_person_in_other_casing_is_not_a_second_invite(self):
        db = self._db()
        self._invite(db, "Shweta.M@Gmail.com")
        again = self._invite(db, "shweta.m@gmail.com")
        assert again["status"] == "already_invited"
        assert len(db.tables["team_invites"]) == 1


class TestSignUpFindsTheInvite:
    """The read side, end to end through the fake Supabase."""

    def test_an_invite_is_accepted_after_sign_up(self):
        db = FakeSupabase(tables={
            "team_invites": [{
                "id": "inv-1", "team_id": "team-1", "email": "shweta.m@gmail.com",
                "invited_by": "owner-1", "status": "pending",
            }],
            "team_members": [],
        })
        assert accept_pending_invites_for_email(db, "user-1", "shweta.m@gmail.com") == 1
        assert db.tables["team_members"][0]["user_id"] == "user-1"
        assert db.tables["team_invites"][0]["status"] == "accepted"

    def test_the_lookup_normalizes_the_address_it_is_given(self):
        """Callers pass whatever they hold. Google sign-in, for one, hands over
        the address as the provider spells it."""
        db = FakeSupabase(tables={
            "team_invites": [{
                "id": "inv-1", "team_id": "team-1", "email": "shweta.m@gmail.com",
                "invited_by": "owner-1", "status": "pending",
            }],
            "team_members": [],
        })
        assert accept_pending_invites_for_email(db, "user-1", " Shweta.M@Gmail.com ") == 1

    def test_someone_else_does_not_get_the_invite(self):
        db = FakeSupabase(tables={
            "team_invites": [{
                "id": "inv-1", "team_id": "team-1", "email": "shweta.m@gmail.com",
                "invited_by": "owner-1", "status": "pending",
            }],
            "team_members": [],
        })
        assert accept_pending_invites_for_email(db, "user-2", "someone.else@gmail.com") == 0
        assert db.tables["team_members"] == []

    def test_an_already_accepted_invite_is_not_re_accepted(self):
        db = FakeSupabase(tables={
            "team_invites": [{
                "id": "inv-1", "team_id": "team-1", "email": "shweta.m@gmail.com",
                "invited_by": "owner-1", "status": "accepted",
            }],
            "team_members": [],
        })
        assert accept_pending_invites_for_email(db, "user-1", "shweta.m@gmail.com") == 0

    def test_the_cached_invite_matches_regardless_of_casing(self):
        _mem_team_invites.append({
            "id": "inv-1", "team_id": "team-1", "email": "Shweta.M@Gmail.com",
            "invited_by": "owner-1", "status": "pending",
        })
        accept_pending_invites_for_email(None, "user-1", "shweta.m@gmail.com")
        assert _mem_team_invites[0]["status"] == "accepted"
        assert {"team_id": "team-1", "user_id": "user-1", "role": "member"} in _mem_team_members


class TestInviteLink:
    def test_plus_addressing_survives_the_link(self):
        """A `+` in a query string decodes to a space, so an un-encoded
        `a+team@gmail.com` reaches the sign-up page as `a team@gmail.com` and
        prefills an address that matches no invite."""
        url = _invite_url("a+team@gmail.com", "team-1")
        assert "a%2Bteam%40gmail.com" in url
        assert "+" not in url.split("invite_email=")[1].split("&")[0]

    def test_the_link_round_trips(self):
        from urllib.parse import urlparse, parse_qs

        url = _invite_url("a+team@gmail.com", "team 1/2")
        params = parse_qs(urlparse(url).query)
        assert params["invite_email"] == ["a+team@gmail.com"]
        assert params["team_id"] == ["team 1/2"]

    def test_the_team_id_cannot_inject_another_parameter(self):
        url = _invite_url("a@b.com", "t1&admin=true")
        assert "&admin=true" not in url

    def test_an_ordinary_address_stays_readable(self):
        url = _invite_url("recruiter@acme.com", "team-1")
        assert "invite_email=recruiter%40acme.com&team_id=team-1" in url
