"""
HireLens — ATS CSV Import Parser

Real recruiter pain point: candidates already live in Greenhouse/Lever/
Workday/BambooHR/etc, and manually re-uploading each resume one at a time
into HireLens is exactly the kind of busywork this tool should eliminate.

Building a live OAuth integration with each ATS vendor isn't realistic on a
$0 budget — most require a paid plan just to access their API (e.g.
Greenhouse's Harvest API), plus a developer-partnership approval process per
vendor. What EVERY ATS supports today, with zero setup, is exporting the
candidate list as CSV — so that's the integration surface: the recruiter
exports from whichever ATS they use, uploads the CSV here, and HireLens
downloads + analyzes every resume URL in it through the exact same pipeline
bulk upload already uses.

Column names differ across ATS exports (Greenhouse says "Attachment URL",
Lever says "Resume", etc.) — this module auto-detects the likely name/email/
resume-URL columns from a broad, case-insensitive alias list rather than
requiring the recruiter to manually map columns for a v1.
"""

import csv
import io
import re

NAME_ALIASES = {"name", "candidate name", "candidate_name", "full name", "full_name", "applicant name", "applicant_name", "candidate"}
EMAIL_ALIASES = {"email", "candidate email", "candidate_email", "email address", "email_address", "e-mail"}
RESUME_URL_ALIASES = {
    "resume_url", "resume url", "resume link", "resume_link", "resume",
    "cv_url", "cv url", "cv link", "cv_link", "cv",
    "attachment_url", "attachment url", "attachment", "attachment_link",
    "document_url", "file_url", "file url",
}

URL_RE = re.compile(r"^https?://", re.IGNORECASE)
MAX_ROWS = 200  # generous cap — actual processing still goes through BULK_MAX_FILES downstream


def _normalize_header(h: str) -> str:
    return h.strip().lower()


def _detect_column(headers: list[str], aliases: set[str]) -> str | None:
    normalized = {h: _normalize_header(h) for h in headers}
    for original, norm in normalized.items():
        if norm in aliases:
            return original
    # Fallback: substring match (e.g. a header like "Resume Download URL")
    for original, norm in normalized.items():
        if any(alias in norm for alias in aliases):
            return original
    return None


def parse_ats_csv(file_bytes: bytes) -> dict:
    """
    Returns:
      {
        "rows": [{"row_num": int, "name": str|None, "email": str|None, "resume_url": str|None}, ...],
        "skipped": [{"row_num": int, "reason": str}, ...],
        "detected_columns": {"name": str|None, "email": str|None, "resume_url": str|None},
      }
    """
    try:
        text = file_bytes.decode("utf-8-sig")  # handles Excel's UTF-8 BOM
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []

    name_col = _detect_column(headers, NAME_ALIASES)
    email_col = _detect_column(headers, EMAIL_ALIASES)
    resume_col = _detect_column(headers, RESUME_URL_ALIASES)

    rows = []
    skipped = []

    for i, raw_row in enumerate(reader, start=2):  # row 1 is the header
        if i - 1 > MAX_ROWS:
            skipped.append({"row_num": i, "reason": f"Exceeds max {MAX_ROWS} rows per import — split into multiple files."})
            continue

        resume_url = (raw_row.get(resume_col) or "").strip() if resume_col else ""
        name = (raw_row.get(name_col) or "").strip() if name_col else ""
        email = (raw_row.get(email_col) or "").strip() if email_col else ""

        if not resume_url:
            skipped.append({"row_num": i, "reason": "No resume URL found in this row."})
            continue
        if not URL_RE.match(resume_url):
            skipped.append({"row_num": i, "reason": f"'{resume_url[:60]}' is not a valid http(s) URL."})
            continue

        rows.append({"row_num": i, "name": name or None, "email": email or None, "resume_url": resume_url})

    return {
        "rows": rows,
        "skipped": skipped,
        "detected_columns": {"name": name_col, "email": email_col, "resume_url": resume_col},
    }
