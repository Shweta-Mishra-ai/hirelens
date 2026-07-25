"""
HireLens — ATS CSV Import Unit Tests
Run: cd backend && python -m pytest tests/unit/test_csv_import.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app.services.parser.csv_import import parse_ats_csv, _detect_column, MAX_ROWS


class TestColumnDetection:
    def test_detects_exact_alias_match(self):
        headers = ["Full Name", "Email", "Resume URL"]
        assert _detect_column(headers, {"full name"}) == "Full Name"

    def test_detects_substring_match_fallback(self):
        headers = ["Resume Download URL"]
        assert _detect_column(headers, {"resume url", "resume"}) == "Resume Download URL"

    def test_no_match_returns_none(self):
        headers = ["Random Column", "Another One"]
        assert _detect_column(headers, {"email"}) is None

    def test_case_insensitive(self):
        headers = ["CANDIDATE EMAIL"]
        assert _detect_column(headers, {"candidate email"}) == "CANDIDATE EMAIL"


class TestParseGreenhouseStyleCsv:
    def test_greenhouse_style_headers(self):
        csv_text = (
            "Candidate Name,Email Address,Attachment URL\n"
            "Jane Doe,jane@example.com,https://example.com/resumes/jane.pdf\n"
            "John Smith,john@example.com,https://example.com/resumes/john.pdf\n"
        )
        result = parse_ats_csv(csv_text.encode("utf-8"))
        assert len(result["rows"]) == 2
        assert result["rows"][0]["name"] == "Jane Doe"
        assert result["rows"][0]["email"] == "jane@example.com"
        assert result["rows"][0]["resume_url"] == "https://example.com/resumes/jane.pdf"
        assert result["detected_columns"]["name"] == "Candidate Name"


class TestParseLeverStyleCsv:
    def test_lever_style_headers(self):
        csv_text = (
            "name,email,resume\n"
            "Alice Wong,alice@example.com,https://lever-files.example.com/alice-resume.pdf\n"
        )
        result = parse_ats_csv(csv_text.encode("utf-8"))
        assert len(result["rows"]) == 1
        assert result["rows"][0]["resume_url"] == "https://lever-files.example.com/alice-resume.pdf"


class TestParseEdgeCases:
    def test_missing_resume_url_column_entirely_skips_all_rows(self):
        csv_text = "name,email\nJane,jane@example.com\n"
        result = parse_ats_csv(csv_text.encode("utf-8"))
        assert result["rows"] == []
        assert len(result["skipped"]) == 1
        assert "No resume URL" in result["skipped"][0]["reason"]

    def test_row_with_empty_resume_url_is_skipped(self):
        csv_text = "name,email,resume_url\nJane,jane@example.com,\nBob,bob@example.com,https://x.com/bob.pdf\n"
        result = parse_ats_csv(csv_text.encode("utf-8"))
        assert len(result["rows"]) == 1
        assert result["rows"][0]["name"] == "Bob"
        assert len(result["skipped"]) == 1

    def test_invalid_url_scheme_is_skipped(self):
        csv_text = "name,resume_url\nJane,ftp://example.com/jane.pdf\n"
        result = parse_ats_csv(csv_text.encode("utf-8"))
        assert result["rows"] == []
        assert "not a valid" in result["skipped"][0]["reason"]

    def test_empty_csv_returns_empty_results(self):
        result = parse_ats_csv(b"name,email,resume_url\n")
        assert result["rows"] == []
        assert result["skipped"] == []

    def test_utf8_bom_handled(self):
        csv_text = "\ufeffname,resume_url\nJane,https://x.com/jane.pdf\n"
        result = parse_ats_csv(csv_text.encode("utf-8"))
        assert len(result["rows"]) == 1
        assert result["rows"][0]["name"] == "Jane"

    def test_row_numbers_account_for_header(self):
        csv_text = "name,resume_url\nJane,https://x.com/jane.pdf\nBob,https://x.com/bob.pdf\n"
        result = parse_ats_csv(csv_text.encode("utf-8"))
        assert result["rows"][0]["row_num"] == 2  # row 1 is header
        assert result["rows"][1]["row_num"] == 3

    def test_missing_name_and_email_columns_still_processes_resume_url(self):
        csv_text = "resume_url\nhttps://x.com/anon.pdf\n"
        result = parse_ats_csv(csv_text.encode("utf-8"))
        assert len(result["rows"]) == 1
        assert result["rows"][0]["name"] is None
        assert result["rows"][0]["resume_url"] == "https://x.com/anon.pdf"

    def test_exceeding_max_rows_are_marked_skipped(self):
        lines = ["name,resume_url"]
        for i in range(MAX_ROWS + 5):
            lines.append(f"Person{i},https://x.com/p{i}.pdf")
        csv_text = "\n".join(lines) + "\n"
        result = parse_ats_csv(csv_text.encode("utf-8"))
        assert len(result["rows"]) == MAX_ROWS
        assert len(result["skipped"]) == 5
        assert "Exceeds max" in result["skipped"][0]["reason"]
