"""
HireLens — Team Member Removal Access-Revocation Regression Test
Run: cd backend && python -m pytest tests/unit/test_team_removal.py -v

Root cause this guards against: `remove_member` and `delete_team` in
teams.py used `global _mem_team_members` and then reassigned it
(`_mem_team_members = [...]`). That only rebinds the name inside teams.py's
own module namespace — it does not touch the list object that
access.py's `get_user_role()` actually reads, since that's a separate
binding of the same original name created by `from ... import
_mem_team_members` at the top of teams.py. Net effect: removing someone
from a team, or deleting a team outright, silently did nothing to their
actual access for as long as the process stayed running, while still
returning {"status": "removed"} / {"status": "deleted"}.

Fixed by mutating the list in place (`lst[:] = [...]`) instead of
rebinding the name, so every module holding a reference sees the same
change to the same underlying object.
"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app.services.teams.access import _mem_team_members, get_user_role


def _cleanup(*team_ids: str):
    _mem_team_members[:] = [m for m in _mem_team_members if m["team_id"] not in team_ids]


class TestRemoveMemberRevokesAccess:
    def test_removed_member_loses_their_role(self):
        from app.api.v1.endpoints.teams import remove_member

        team_id = "test-f02-remove"
        owner_id = "test-f02-owner-a"
        member_id = "test-f02-member-a"

        _mem_team_members.append({"team_id": team_id, "user_id": owner_id, "role": "owner", "joined_at": "now"})
        _mem_team_members.append({"team_id": team_id, "user_id": member_id, "role": "member", "joined_at": "now"})

        try:
            assert get_user_role(None, team_id, member_id) == "member"

            asyncio.run(remove_member(team_id, member_id, current_user={"id": owner_id}, db=None))

            # This is the exact assertion that failed before the fix — the
            # role stayed "member" indefinitely because the mutation never
            # reached the list access.py actually queries.
            assert get_user_role(None, team_id, member_id) is None
        finally:
            _cleanup(team_id)

    def test_owner_role_is_unaffected_by_removing_a_different_member(self):
        from app.api.v1.endpoints.teams import remove_member

        team_id = "test-f02-remove-2"
        owner_id = "test-f02-owner-b"
        member_id = "test-f02-member-b"

        _mem_team_members.append({"team_id": team_id, "user_id": owner_id, "role": "owner", "joined_at": "now"})
        _mem_team_members.append({"team_id": team_id, "user_id": member_id, "role": "member", "joined_at": "now"})

        try:
            asyncio.run(remove_member(team_id, member_id, current_user={"id": owner_id}, db=None))
            assert get_user_role(None, team_id, owner_id) == "owner"
        finally:
            _cleanup(team_id)

    def test_removing_from_one_team_does_not_affect_membership_in_another(self):
        from app.api.v1.endpoints.teams import remove_member

        team_a, team_b = "test-f02-team-a", "test-f02-team-b"
        owner_id, member_id = "test-f02-owner-c", "test-f02-member-c"

        _mem_team_members.append({"team_id": team_a, "user_id": owner_id, "role": "owner", "joined_at": "now"})
        _mem_team_members.append({"team_id": team_a, "user_id": member_id, "role": "member", "joined_at": "now"})
        _mem_team_members.append({"team_id": team_b, "user_id": member_id, "role": "member", "joined_at": "now"})

        try:
            asyncio.run(remove_member(team_a, member_id, current_user={"id": owner_id}, db=None))
            assert get_user_role(None, team_a, member_id) is None
            assert get_user_role(None, team_b, member_id) == "member"  # untouched
        finally:
            _cleanup(team_a, team_b)


class TestDeleteTeamRevokesAllAccess:
    def test_deleting_team_removes_every_members_role(self):
        from app.api.v1.endpoints.teams import delete_team

        team_id = "test-f02-delete"
        owner_id = "test-f02-owner-d"
        member_id = "test-f02-member-d"

        _mem_team_members.append({"team_id": team_id, "user_id": owner_id, "role": "owner", "joined_at": "now"})
        _mem_team_members.append({"team_id": team_id, "user_id": member_id, "role": "member", "joined_at": "now"})

        try:
            asyncio.run(delete_team(team_id, current_user={"id": owner_id}, db=None))
            assert get_user_role(None, team_id, owner_id) is None
            assert get_user_role(None, team_id, member_id) is None
        finally:
            _cleanup(team_id)
