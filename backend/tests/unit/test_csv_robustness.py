"""
ATS CSV import robustness.

`csv` raises on a field over its internal 131072-character limit, and that
error escaped `parse_ats_csv` entirely — so one oversized cell in an uploaded
export turned into an unhandled 500 rather than a skipped row. A NUL byte had
a subtler effect: it makes the reader treat the file as one broken record, so
a whole import silently produced nothing.
"""

import pytest

from app.core.exceptions import ValidationError
from app.services.parser.csv_import import parse_ats_csv

HEADER = b"Name,Email,Resume URL\n"


def test_a_normal_export_parses():
    out = parse_ats_csv(HEADER + b"Priya R,p@x.com,https://ex.com/a.pdf\n")
    assert len(out["rows"]) == 1
    assert out["rows"][0]["name"] == "Priya R"
    assert out["rows"][0]["resume_url"] == "https://ex.com/a.pdf"


@pytest.mark.parametrize(
    "headers",
    [
        b"Candidate Name,Email,Resume URL\n",
        b"name,email,resume\n",
        b"Full Name,Email Address,CV Link\n",
    ],
)
def test_common_ats_header_spellings_are_detected(headers):
    out = parse_ats_csv(headers + b"X,x@x.com,https://ex.com/a.pdf\n")
    assert len(out["rows"]) == 1, out["detected_columns"]


def test_an_oversized_field_is_a_skipped_row_not_a_crash():
    data = HEADER + b"A" * 200_000 + b",x@x.com,https://ex.com/e.pdf\n"
    out = parse_ats_csv(data)  # must not raise
    assert out["rows"] == []
    assert len(out["skipped"]) == 1
    assert "oversized" in out["skipped"][0]["reason"].lower()


def test_nul_bytes_do_not_swallow_the_file():
    out = parse_ats_csv(HEADER + b"X\x00Y,x@x.com,https://ex.com/c.pdf\n")
    assert len(out["rows"]) == 1


def test_binary_input_yields_no_rows_rather_than_raising():
    out = parse_ats_csv(b"\x00\x01\x02not a csv at all")
    assert out["rows"] == []


def test_latin1_fallback_for_non_utf8_exports():
    data = "Name,Email,Resume URL\nJosé Muñoz,j@x.com,https://ex.com/d.pdf\n".encode("latin-1")
    out = parse_ats_csv(data)
    assert len(out["rows"]) == 1


def test_empty_file():
    out = parse_ats_csv(b"")
    assert out["rows"] == []


def test_headers_only():
    out = parse_ats_csv(HEADER)
    assert out["rows"] == []
    assert out["skipped"] == []


@pytest.mark.parametrize(
    "url",
    [
        b"file:///etc/passwd",
        b"javascript:alert(1)",
        b"ftp://example.com/cv.pdf",
        b"not-a-url",
        b"",
    ],
)
def test_non_http_resume_urls_are_skipped(url):
    out = parse_ats_csv(HEADER + b"X,x@x.com," + url + b"\n")
    assert out["rows"] == []
    assert len(out["skipped"]) == 1


def test_rows_missing_a_resume_url_are_reported_individually():
    data = HEADER + b"A,a@x.com,https://ex.com/a.pdf\nB,b@x.com,\nC,c@x.com,https://ex.com/c.pdf\n"
    out = parse_ats_csv(data)
    assert len(out["rows"]) == 2
    assert len(out["skipped"]) == 1
    assert out["skipped"][0]["row_num"] == 3


def test_row_numbers_match_the_spreadsheet():
    """Row 1 is the header, so the first data row is row 2 — what the user sees."""
    out = parse_ats_csv(HEADER + b"A,a@x.com,https://ex.com/a.pdf\n")
    assert out["rows"][0]["row_num"] == 2
