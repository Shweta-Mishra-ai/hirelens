"""
ATS CSV import, end to end with a mocked network.

This endpoint is the one that takes an untrusted list of URLs out of an
uploaded CSV and fetches every one of them. It had the lowest coverage in
the codebase, which is the wrong place to have it: the download path is
both attacker-reachable (any URL a CSV names) and the only place a single
bad row can decide whether a whole import produces anything.

Nothing here touches the network — httpx runs on a MockTransport.
"""

import io

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints import ats
from app.core.exceptions import HireLensException
from app.main import app

client = TestClient(app)

PDF = b"%PDF-1.4\n" + b"0" * 2048
HEADER = b"Name,Email,Resume URL\n"


@pytest.fixture
def headers():
    creds = {"email": "ats_import@example.com", "password": "Password123!"}
    res = client.post("/api/v1/auth/signup", json={**creds, "full_name": "ATS Tester"})
    if res.status_code == 409:
        res = client.post("/api/v1/auth/login", json=creds)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def network(monkeypatch):
    """Replace the module's httpx client with a scripted transport.

    Returns a setter so each test decides what the internet says.
    """
    state = {"handler": lambda request: httpx.Response(200, content=PDF)}
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(lambda r: state["handler"](r))
        return real(*args, **kwargs)

    monkeypatch.setattr(ats.httpx, "AsyncClient", factory)
    monkeypatch.setattr(ats, "is_public_http_url", lambda url: url.startswith(("http://", "https://")))
    return state


@pytest.fixture(autouse=True)
def no_background_analysis(monkeypatch):
    """The batch runner would call the LLM; the import itself is what's under test."""
    async def noop(**kwargs):
        return None

    monkeypatch.setattr(ats, "_run_batch", noop)


def csv_file(body: bytes):
    return {"file": ("export.csv", io.BytesIO(body), "text/csv")}


class TestDownload:
    @pytest.mark.asyncio
    async def test_a_plain_download_returns_the_bytes(self, network):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=PDF))) as c:
            assert await ats._download_resume(c, "https://ats.example/a.pdf") == PDF

    @pytest.mark.asyncio
    async def test_a_non_public_url_is_refused_without_a_request(self, monkeypatch):
        seen = []

        def handler(request):
            seen.append(str(request.url))
            return httpx.Response(200, content=PDF)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            with pytest.raises(HireLensException) as err:
                await ats._download_resume(c, "http://169.254.169.254/latest/meta-data/")
        assert err.value.http_status == 422
        assert seen == []

    @pytest.mark.asyncio
    async def test_a_redirect_to_an_internal_address_is_refused_mid_chain(self, monkeypatch):
        seen = []

        def handler(request):
            seen.append(request.url.host)
            if request.url.host == "ats.example":
                return httpx.Response(302, headers={"location": "http://169.254.169.254/"})
            return httpx.Response(200, content=PDF)

        monkeypatch.setattr(
            ats, "is_public_http_url",
            lambda url: "169.254.169.254" not in url and url.startswith(("http://", "https://")),
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            with pytest.raises(HireLensException):
                await ats._download_resume(c, "https://ats.example/a.pdf")
        assert "169.254.169.254" not in seen

    @pytest.mark.asyncio
    async def test_a_safe_redirect_is_followed(self, monkeypatch):
        monkeypatch.setattr(ats, "is_public_http_url", lambda url: url.startswith(("http://", "https://")))

        def handler(request):
            if request.url.path == "/a.pdf":
                return httpx.Response(302, headers={"location": "/real.pdf"})
            return httpx.Response(200, content=PDF)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            assert await ats._download_resume(c, "https://ats.example/a.pdf") == PDF

    @pytest.mark.asyncio
    async def test_a_redirect_without_a_location_header_is_an_error(self, monkeypatch):
        monkeypatch.setattr(ats, "is_public_http_url", lambda url: True)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(302))) as c:
            with pytest.raises(HireLensException):
                await ats._download_resume(c, "https://ats.example/a.pdf")

    @pytest.mark.asyncio
    async def test_an_endless_redirect_chain_gives_up(self, monkeypatch):
        monkeypatch.setattr(ats, "is_public_http_url", lambda url: True)
        hops = []

        def handler(request):
            hops.append(1)
            return httpx.Response(302, headers={"location": "https://ats.example/next"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            with pytest.raises(HireLensException) as err:
                await ats._download_resume(c, "https://ats.example/a.pdf")
        assert "redirects" in str(err.value.message).lower()
        assert len(hops) <= ats._MAX_REDIRECT_HOPS + 1

    @pytest.mark.asyncio
    async def test_a_404_is_reported_with_its_status(self, monkeypatch):
        monkeypatch.setattr(ats, "is_public_http_url", lambda url: True)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))) as c:
            with pytest.raises(HireLensException) as err:
                await ats._download_resume(c, "https://ats.example/gone.pdf")
        assert "404" in str(err.value.message)

    @pytest.mark.asyncio
    async def test_an_oversized_body_aborts_instead_of_buffering(self, monkeypatch):
        """The cap must bound memory, so it has to bite while streaming — not
        after the whole body is already in the process."""
        monkeypatch.setattr(ats, "is_public_http_url", lambda url: True)
        monkeypatch.setattr(ats, "MAX_DOWNLOAD_MB", 1)
        chunks_served = []

        async def stream():
            for _ in range(8):
                chunks_served.append(1)
                yield b"x" * (512 * 1024)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=stream()))
        ) as c:
            with pytest.raises(HireLensException) as err:
                await ats._download_resume(c, "https://ats.example/huge.pdf")
        assert "exceeds" in str(err.value.message)
        assert len(chunks_served) < 8


class TestFilenames:
    def test_the_candidate_name_becomes_the_filename(self):
        assert ats._filename_for_row({"name": "Priya Raghavan", "row_num": 2}) == "Priya Raghavan.pdf"

    def test_path_characters_are_stripped_out(self):
        out = ats._filename_for_row({"name": "../../etc/passwd", "row_num": 2})
        assert "/" not in out and ".." not in out

    def test_a_nameless_row_falls_back_to_its_row_number(self):
        assert ats._filename_for_row({"name": "", "row_num": 7}) == "candidate_row7.pdf"
        assert ats._filename_for_row({"name": "!!!", "row_num": 7}) == "candidate_row7.pdf"


class TestImportEndpoint:
    def test_import_requires_authentication(self):
        res = client.post("/api/v1/ats/import", files=csv_file(HEADER))
        assert res.status_code in (401, 403)

    def test_an_upload_with_no_content_is_rejected(self, headers, network):
        res = client.post("/api/v1/ats/import", headers=headers, files=csv_file(b""))
        assert res.status_code == 422, res.text
        assert res.json()["error"] == "empty_batch"

    def test_a_csv_with_no_usable_rows_is_rejected(self, headers, network):
        res = client.post("/api/v1/ats/import", headers=headers, files=csv_file(HEADER))
        assert res.status_code == 422, res.text
        assert res.json()["error"] == "empty_batch"

    def test_a_good_csv_queues_a_batch(self, headers, network):
        body = HEADER + (
            b"Priya R,p@x.com,https://ats.example/1.pdf\n"
            b"Arjun M,a@x.com,https://ats.example/2.pdf\n"
        )
        res = client.post("/api/v1/ats/import", headers=headers, files=csv_file(body))
        assert res.status_code == 200, res.text
        payload = res.json()
        assert payload["queued"] == 2
        assert payload["total_rows"] == 2
        assert payload["batch_id"]
        assert payload["skipped_at_download"] == []

    def test_the_queued_batch_is_pollable_through_the_bulk_endpoints(self, headers, network):
        body = HEADER + b"Priya R,p@x.com,https://ats.example/1.pdf\n"
        res = client.post("/api/v1/ats/import", headers=headers, files=csv_file(body))
        batch_id = res.json()["batch_id"]
        status = client.get(f"/api/v1/bulk/{batch_id}/status", headers=headers)
        assert status.status_code == 200
        assert status.json()["total"] == 1

    def test_one_dead_url_does_not_sink_the_whole_import(self, headers, network):
        def handler(request):
            if request.url.path == "/dead.pdf":
                return httpx.Response(404)
            return httpx.Response(200, content=PDF)

        network["handler"] = handler
        body = HEADER + (
            b"Priya R,p@x.com,https://ats.example/ok.pdf\n"
            b"Ghost G,g@x.com,https://ats.example/dead.pdf\n"
        )
        res = client.post("/api/v1/ats/import", headers=headers, files=csv_file(body))
        assert res.status_code == 200, res.text
        payload = res.json()
        assert payload["queued"] == 1
        assert len(payload["skipped_at_download"]) == 1
        assert payload["skipped_at_download"][0]["row_num"] == 3

    def test_an_import_where_every_url_is_dead_says_so(self, headers, network):
        network["handler"] = lambda request: httpx.Response(500)
        body = HEADER + b"Ghost G,g@x.com,https://ats.example/dead.pdf\n"
        res = client.post("/api/v1/ats/import", headers=headers, files=csv_file(body))
        assert res.status_code == 422
        assert res.json()["error"] == "all_resumes_unreachable"

    def test_a_failed_import_leaves_no_orphaned_jobs(self, headers, network):
        from app.api.v1.endpoints.analysis import _jobs

        network["handler"] = lambda request: httpx.Response(500)
        before = len(_jobs)
        body = HEADER + b"Ghost G,g@x.com,https://ats.example/dead.pdf\n"
        client.post("/api/v1/ats/import", headers=headers, files=csv_file(body))
        assert len(_jobs) == before

    def test_a_row_serving_something_that_is_not_a_resume_is_skipped(self, headers, network):
        network["handler"] = lambda request: httpx.Response(200, content=b"<html>Not found</html>")
        body = HEADER + b"Priya R,p@x.com,https://ats.example/page.html\n"
        res = client.post("/api/v1/ats/import", headers=headers, files=csv_file(body))
        assert res.status_code == 422
        assert res.json()["error"] == "all_resumes_unreachable"

    def test_rows_the_parser_skipped_are_reported_back(self, headers, network):
        body = HEADER + (
            b"Priya R,p@x.com,https://ats.example/1.pdf\n"
            b"No URL Here,n@x.com,\n"
        )
        res = client.post("/api/v1/ats/import", headers=headers, files=csv_file(body))
        assert res.status_code == 200, res.text
        payload = res.json()
        assert payload["queued"] == 1
        assert len(payload["skipped_at_parse"]) == 1
        assert payload["total_rows"] == 2
