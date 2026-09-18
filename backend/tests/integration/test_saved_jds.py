"""
HireLens — Saved job descriptions

A job description is written once and used against every shortlist for that
role. The thing that matters most here is that a saved description belongs to
exactly one recruiter, and that a batch is ranked against the text that was
actually stored — a ranking against the wrong description is confidently wrong
about every candidate on the list.

Run: cd backend && python -m pytest tests/integration/test_saved_jds.py -v
"""
import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import get_db
from app.main import app
from tests.fake_supabase import FakeSupabase

client = TestClient(app)

JD = "We are hiring a senior backend engineer with Python, Postgres and Kafka experience."


def signup(email):
    creds = {"email": email, "password": "JdPassword123!"}
    res = client.post("/api/v1/auth/signup", json={**creds, "full_name": "Jd User"})
    if res.status_code == 409:
        res = client.post("/api/v1/auth/login", json=creds)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def owner():
    return signup("jd_owner@example.com")


@pytest.fixture
def other():
    return signup("jd_other@example.com")


@pytest.fixture(autouse=True)
def clean_jds():
    from app.core import local_db
    with local_db._get_connection() as conn:
        conn.execute("DELETE FROM saved_jds")
        conn.commit()
    yield
    with local_db._get_connection() as conn:
        conn.execute("DELETE FROM saved_jds")
        conn.commit()


class TestSavingAndReusing:
    def test_a_description_can_be_saved_and_read_back(self, owner):
        res = client.post("/api/v1/job-descriptions", headers=owner,
                          json={"name": "Senior Backend Engineer", "jd_text": JD})
        assert res.status_code == 201, res.text
        jd_id = res.json()["job_description"]["id"]

        fetched = client.get(f"/api/v1/job-descriptions/{jd_id}", headers=owner)
        assert fetched.status_code == 200
        assert fetched.json()["job_description"]["jd_text"] == JD

    def test_the_list_leaves_the_text_out(self, owner):
        client.post("/api/v1/job-descriptions", headers=owner,
                    json={"name": "Senior Backend Engineer", "jd_text": JD})
        rows = client.get("/api/v1/job-descriptions", headers=owner).json()["job_descriptions"]
        assert len(rows) == 1
        # Twenty job descriptions is a lot to send to render a list of names.
        assert "jd_text" not in rows[0]
        assert rows[0]["char_count"] == len(JD)

    def test_saving_under_the_same_name_replaces_rather_than_duplicates(self, owner):
        client.post("/api/v1/job-descriptions", headers=owner,
                    json={"name": "Senior Backend Engineer", "jd_text": JD})
        revised = JD + " Kubernetes is now required too."
        client.post("/api/v1/job-descriptions", headers=owner,
                    json={"name": "Senior Backend Engineer", "jd_text": revised})

        rows = client.get("/api/v1/job-descriptions", headers=owner).json()["job_descriptions"]
        assert len(rows) == 1, "a revised description must not become a second entry"
        jd_id = rows[0]["id"]
        assert client.get(f"/api/v1/job-descriptions/{jd_id}", headers=owner).json()[
            "job_description"]["jd_text"] == revised

    def test_the_name_it_was_first_saved_under_is_kept(self, owner):
        """Otherwise the list shows one spelling and the save response another,
        and the recruiter cannot find what they just saved."""
        client.post("/api/v1/job-descriptions", headers=owner,
                    json={"name": "Senior Backend Engineer", "jd_text": JD})
        again = client.post("/api/v1/job-descriptions", headers=owner,
                            json={"name": "senior backend engineer", "jd_text": JD + " Revised."})
        assert again.json()["job_description"]["name"] == "Senior Backend Engineer"

    def test_deleting_one_removes_it(self, owner):
        jd_id = client.post("/api/v1/job-descriptions", headers=owner,
                            json={"name": "Temp Role", "jd_text": JD}).json()["job_description"]["id"]
        assert client.delete(f"/api/v1/job-descriptions/{jd_id}", headers=owner).status_code == 200
        assert client.get("/api/v1/job-descriptions", headers=owner).json()["job_descriptions"] == []
        assert client.delete(f"/api/v1/job-descriptions/{jd_id}", headers=owner).status_code == 404


class TestOneRecruitersDescriptionsAreTheirOwn:
    def test_another_recruiter_cannot_read_it_by_id(self, owner, other):
        jd_id = client.post("/api/v1/job-descriptions", headers=owner,
                            json={"name": "Confidential Role", "jd_text": JD}).json()["job_description"]["id"]
        assert client.get(f"/api/v1/job-descriptions/{jd_id}", headers=other).status_code == 404

    def test_another_recruiter_does_not_see_it_listed(self, owner, other):
        client.post("/api/v1/job-descriptions", headers=owner,
                    json={"name": "Confidential Role", "jd_text": JD})
        assert client.get("/api/v1/job-descriptions", headers=other).json()["job_descriptions"] == []

    def test_another_recruiter_cannot_delete_it(self, owner, other):
        jd_id = client.post("/api/v1/job-descriptions", headers=owner,
                            json={"name": "Confidential Role", "jd_text": JD}).json()["job_description"]["id"]
        assert client.delete(f"/api/v1/job-descriptions/{jd_id}", headers=other).status_code == 404
        # ...and it is still there for its owner.
        assert client.get(f"/api/v1/job-descriptions/{jd_id}", headers=owner).status_code == 200

    def test_two_recruiters_can_use_the_same_name(self, owner, other):
        a = client.post("/api/v1/job-descriptions", headers=owner,
                        json={"name": "Backend Engineer", "jd_text": JD})
        b = client.post("/api/v1/job-descriptions", headers=other,
                        json={"name": "Backend Engineer", "jd_text": JD + " Different company."})
        assert a.status_code == 201 and b.status_code == 201
        assert a.json()["job_description"]["id"] != b.json()["job_description"]["id"]

    def test_signing_in_is_required(self):
        assert client.get("/api/v1/job-descriptions").status_code == 401
        assert client.post("/api/v1/job-descriptions",
                           json={"name": "X", "jd_text": JD}).status_code == 401


class TestWhatIsRejected:
    def test_a_description_too_short_to_match_against(self, owner):
        res = client.post("/api/v1/job-descriptions", headers=owner,
                          json={"name": "Tiny", "jd_text": "short"})
        assert res.status_code == 422
        assert "30 characters" in res.json()["message"]

    def test_a_nameless_description(self, owner):
        res = client.post("/api/v1/job-descriptions", headers=owner,
                          json={"name": "   ", "jd_text": JD})
        assert res.status_code == 422

    def test_an_over_long_name(self, owner):
        res = client.post("/api/v1/job-descriptions", headers=owner,
                          json={"name": "x" * 200, "jd_text": JD})
        assert res.status_code == 422

    def test_text_is_capped_at_the_length_the_matcher_uses(self, owner):
        """What is saved has to be what gets used. A description truncated at
        match time would rank candidates against text nobody ever saw."""
        from app.core.config import settings
        huge = "Senior engineer. " * 2000
        jd_id = client.post("/api/v1/job-descriptions", headers=owner,
                            json={"name": "Huge", "jd_text": huge}).json()["job_description"]["id"]
        stored = client.get(f"/api/v1/job-descriptions/{jd_id}", headers=owner).json()
        assert len(stored["job_description"]["jd_text"]) <= settings.JD_MAX_CHARS

    def test_a_missing_description_is_not_found(self, owner):
        assert client.get("/api/v1/job-descriptions/00000000-0000-0000-0000-000000000000",
                          headers=owner).status_code == 404


class TestUsingOneForAMatchRun:
    @pytest.mark.asyncio
    async def test_a_saved_id_resolves_to_its_stored_text(self, owner):
        """The point of the whole feature: a run ranks against the stored
        text, not against whatever was typed this morning."""
        from app.api.v1.endpoints.match import _resolve_jd_text
        from app.core.security import decode_token

        created = client.post("/api/v1/job-descriptions", headers=owner,
                              json={"name": "Resolve Me", "jd_text": JD}).json()
        jd_id = created["job_description"]["id"]
        user_id = decode_token(owner["Authorization"].split(" ", 1)[1])["sub"]

        resolved = await _resolve_jd_text(None, None, jd_id, user_id, None)
        assert resolved == JD

    @pytest.mark.asyncio
    async def test_a_saved_id_wins_over_pasted_text(self, owner):
        """Choosing a saved description and leaving stale text in the box must
        not silently rank against the stale text."""
        from app.api.v1.endpoints.match import _resolve_jd_text
        from app.core.security import decode_token

        created = client.post("/api/v1/job-descriptions", headers=owner,
                              json={"name": "Wins", "jd_text": JD}).json()
        jd_id = created["job_description"]["id"]
        user_id = decode_token(owner["Authorization"].split(" ", 1)[1])["sub"]

        resolved = await _resolve_jd_text(
            "a completely different job description, long enough to be accepted",
            None, jd_id, user_id, None,
        )
        assert resolved == JD

    @pytest.mark.asyncio
    async def test_using_one_records_that_it_was_used(self, owner):
        from app.api.v1.endpoints.match import _resolve_jd_text
        from app.core import local_db
        from app.core.security import decode_token

        created = client.post("/api/v1/job-descriptions", headers=owner,
                              json={"name": "Track Me", "jd_text": JD}).json()
        jd_id = created["job_description"]["id"]
        user_id = decode_token(owner["Authorization"].split(" ", 1)[1])["sub"]

        assert local_db.get_jd(jd_id, user_id)["last_used_at"] is None
        await _resolve_jd_text(None, None, jd_id, user_id, None)
        assert local_db.get_jd(jd_id, user_id)["last_used_at"] is not None

    @pytest.mark.asyncio
    async def test_someone_elses_saved_id_is_refused(self):
        from app.api.v1.endpoints.match import _resolve_jd_text
        from app.core.exceptions import NotFoundError

        with pytest.raises(NotFoundError):
            await _resolve_jd_text(None, None, "some-id", "not-the-owner", None)

    @pytest.mark.asyncio
    async def test_an_unknown_saved_id_does_not_fall_back_to_other_input(self):
        """Falling through to whatever else was sent would rank the shortlist
        against a description the recruiter did not choose."""
        from app.api.v1.endpoints.match import _resolve_jd_text
        from app.core.exceptions import NotFoundError

        with pytest.raises(NotFoundError):
            await _resolve_jd_text("some other job description text that is long enough",
                                   None, "missing-id", "user-1", None)
