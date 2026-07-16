"""
HireLens — Resume-Likeness Heuristic

Before Feature-fix: HireLens accepted ANY valid PDF/DOCX (invoices, books,
random documents) and ran full AI credibility analysis on it — wasting AI
calls and producing nonsense reports. This module adds a fast, free,
pre-AI content check so obviously-non-resume files are rejected with a
clear error instead of silently "analyzed".

Deliberately conservative: real resumes almost always have at least 2 of
the 3 signals below, so false rejections of legitimate resumes should be
rare. This is a heuristic gate, not a classifier — it's meant to catch
"this is clearly not a resume" cases (a novel, an invoice, a slide deck
export), not to be a perfect filter.
"""

import re

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(\+?\d[\d\-[ \t]()]{7,}\d)")
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

SECTION_HEADERS = [
    "experience", "employment", "work history", "professional experience",
    "education", "academic background", "skills", "technical skills",
    "projects", "summary", "objective", "certification", "certifications",
    "qualification", "qualifications", "profile", "career", "achievements",
    "publications", "internship", "portfolio",
]

MIN_TEXT_LENGTH = 80


def looks_like_resume(text: str) -> tuple[bool, str]:
    """Returns (is_probably_a_resume, rejection_reason_if_not)."""
    if not text or len(text.strip()) < MIN_TEXT_LENGTH:
        return False, (
            "This file doesn't have enough readable text to be a resume "
            "(it may be a scanned image, a blank page, or a corrupted file)."
        )

    lower = text.lower()

    has_contact = bool(EMAIL_RE.search(text)) or bool(PHONE_RE.search(text))
    
    # Stand-alone headers only (at start of line/preceded by space/newlines, followed by punctuation/newlines/spaces)
    header_hits = 0
    for h in SECTION_HEADERS:
        pattern = r"(?:^|\n)\s*(?:professional\s+|technical\s+|work\s+|academic\s+|career\s+)?{}(?:\s*[:\-\n]|\s*$)".format(re.escape(h))
        if re.search(pattern, lower):
            header_hits += 1

    year_hits = len(YEAR_RE.findall(text))

    signals_present = int(has_contact) + int(header_hits >= 2) + int(year_hits >= 2)

    # A valid resume must have at least 2 signals, and must have section headers:
    # - If it has contact details, it needs at least 1 section header (e.g. Skills or Education).
    # - If it has no contact details, it needs at least 2 section headers.
    # This prevents research papers/general documents with emails/dates but no CV structure from passing.
    if signals_present >= 2 and ((has_contact and header_hits >= 1) or (header_hits >= 2)):
        return True, ""

    return False, (
        "This doesn't look like a resume/CV — no contact details, resume "
        "section headers (Experience, Education, Skills, etc.), or work-history "
        "dates were found. Please upload an actual resume in PDF or DOCX format."
    )
