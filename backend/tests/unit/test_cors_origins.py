"""
An origin that looks right in a dashboard but never matches.

A browser's `Origin` header is scheme + host + optional port. Nothing else.
Starlette's CORSMiddleware compares it to the configured list with exact
string equality, so a single trailing slash blocks the entire frontend — and
the failure leaves no trace anywhere: the browser refuses to send the request,
so there is no log line on this API, no request id, and nothing in Supabase
either. The only symptom is "sign-in does nothing".

These pin every shape someone actually types into Render or Vercel.
"""

import pytest

from app.core.config import normalize_origin, parse_origins


SITE = "https://hirelens-theta.vercel.app"


class TestTheShapesPeopleActuallyType:
    @pytest.mark.parametrize(
        "typed",
        [
            "https://hirelens-theta.vercel.app",
            "https://hirelens-theta.vercel.app/",          # the classic
            "https://hirelens-theta.vercel.app///",
            "  https://hirelens-theta.vercel.app  ",
            '"https://hirelens-theta.vercel.app"',          # quotes from an example
            "'https://hirelens-theta.vercel.app'",
            "HTTPS://HireLens-Theta.Vercel.App",            # copied mixed case
            "https://hirelens-theta.vercel.app/login",      # pasted the current page
            "hirelens-theta.vercel.app",                    # scheme left off
        ],
    )
    def test_every_one_of_them_resolves_to_the_same_origin(self, typed):
        assert parse_origins(typed) == [SITE]


class TestSeparators:
    @pytest.mark.parametrize(
        "typed",
        [
            "http://localhost:3000,https://hirelens-theta.vercel.app",
            "http://localhost:3000, https://hirelens-theta.vercel.app",
            "http://localhost:3000;https://hirelens-theta.vercel.app",
            "http://localhost:3000 https://hirelens-theta.vercel.app",
            "http://localhost:3000\nhttps://hirelens-theta.vercel.app",
            '["http://localhost:3000","https://hirelens-theta.vercel.app"]',
            '["http://localhost:3000", "https://hirelens-theta.vercel.app/"]',
        ],
    )
    def test_a_list_is_read_the_same_way_however_it_is_separated(self, typed):
        assert parse_origins(typed) == ["http://localhost:3000", SITE]

    def test_malformed_json_falls_back_instead_of_losing_everything(self):
        # A missing closing bracket used to make the whole value one origin.
        assert parse_origins('["http://localhost:3000"') == ["http://localhost:3000"]


class TestPorts:
    def test_the_port_is_part_of_the_origin_and_is_kept(self):
        assert parse_origins("http://localhost:3000") == ["http://localhost:3000"]

    def test_different_ports_are_different_origins(self):
        assert parse_origins("http://localhost:3000,http://localhost:3001") == [
            "http://localhost:3000",
            "http://localhost:3001",
        ]


class TestDuplicatesAndOrder:
    def test_the_same_origin_written_two_ways_appears_once(self):
        assert parse_origins(f"{SITE},{SITE}/,HTTPS://HIRELENS-THETA.VERCEL.APP") == [SITE]

    def test_order_is_preserved(self):
        assert parse_origins(f"{SITE},http://localhost:3000") == [
            SITE,
            "http://localhost:3000",
        ]


class TestEdges:
    def test_empty_falls_back_to_local_development(self):
        assert parse_origins("") == ["http://localhost:3000"]
        assert parse_origins("   ") == ["http://localhost:3000"]

    def test_wildcard_is_passed_through_for_the_startup_check_to_refuse(self):
        # main.py refuses to boot on '*' in production; it must reach it intact.
        assert "*" in parse_origins("*")

    def test_an_unusable_entry_is_dropped_rather_than_breaking_the_rest(self):
        assert normalize_origin("https://") is None
        assert parse_origins(f"https://,{SITE}") == [SITE]

    def test_http_is_not_silently_upgraded(self):
        """Local development is http, and rewriting it would break it."""
        assert parse_origins("http://localhost:3000") == ["http://localhost:3000"]


class TestItActuallyLetsTheBrowserThrough:
    """
    The property that matters: a request carrying the browser's real Origin
    header is answered with a matching allow-origin, for a value configured
    with a trailing slash.
    """

    def test_a_trailing_slash_no_longer_blocks_the_whole_frontend(self, monkeypatch):
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.add_middleware(
            CORSMiddleware,
            allow_origins=parse_origins(f"{SITE}/"),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        @app.post("/api/v1/auth/login")
        def login():
            return {"ok": True}

        client = TestClient(app)

        preflight = client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": SITE,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers.get("access-control-allow-origin") == SITE

        res = client.post("/api/v1/auth/login", headers={"Origin": SITE})
        assert res.headers.get("access-control-allow-origin") == SITE

    def test_an_unlisted_origin_is_still_refused(self):
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.add_middleware(CORSMiddleware, allow_origins=parse_origins(SITE))

        @app.get("/x")
        def x():
            return {"ok": True}

        res = TestClient(app).get("/x", headers={"Origin": "https://evil.example"})
        assert res.headers.get("access-control-allow-origin") != "https://evil.example"
