"""
Shape guards for stored analysis reports.

A report is a JSON blob. Everything that reads one — the dashboard list,
the report page, ranking, verification, the co-pilot — reaches into it with
`blob.get("candidate") or {}`, which handles a missing or null field but
not a field of the wrong type. A blob whose `candidate` is a string, or
whose `flags` is a string rather than a list, therefore raised
AttributeError deep inside a list comprehension.

That is not a hypothetical. It took down the whole dashboard, not just the
one candidate: `GET /reports` builds its response by walking every report
the user owns, so a single malformed blob returned 500 for the entire list
and the recruiter saw no candidates at all. And because an unhandled
exception bypasses the CORS middleware, the browser could not even read
the error — it reported a CORS failure and the page showed an empty state
with no message.

Blobs get malformed for ordinary reasons: a build that wrote a different
shape, a partial write, a field an older version did not have. So the
guard belongs where a blob is read, not at each of the thirty-odd places
that reach into one.
"""

from typing import Any

# Sub-objects every reader expects to be a mapping.
_DICT_FIELDS = (
    "candidate",
    "skills",
    "credibility",
    "ai_content_analysis",
    "career_trajectory",
    "verification",
    "trust_score",
    "copilot_data",
    "jd_match",
)

# Sub-objects every reader iterates over.
_LIST_FIELDS = (
    "experience",
    "education",
    "projects",
    "certifications",
    "flags",
    "positive_signals",
    "interview_questions",
    "timeline_gaps",
)


def as_dict(value: Any) -> dict:
    """The value if it is a mapping, an empty one otherwise."""
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list:
    """
    The value if it is a list, an empty one otherwise.

    Deliberately not `list(value)`: a string is iterable, so that would
    turn "abc" into three single-character entries — three flags on a
    candidate's file that nobody wrote.
    """
    return value if isinstance(value, list) else []


def as_str(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def as_score(value: Any, default: int = 0, low: int = 0, high: int = 100) -> int:
    """A whole number inside the range, or the default."""
    if isinstance(value, bool):  # bool is a subclass of int
        return default
    if isinstance(value, (int, float)):
        try:
            return max(low, min(high, int(value)))
        except (ValueError, OverflowError):
            return default
    if isinstance(value, str):
        try:
            return max(low, min(high, int(float(value.strip()))))
        except (ValueError, OverflowError):
            return default
    return default


def normalize_report(blob: Any) -> dict:
    """
    Return the blob with its structural fields coerced to the types every
    reader assumes. Unknown keys are passed through untouched — this fixes
    the shape, it does not decide what a report may contain.
    """
    if not isinstance(blob, dict):
        return {}

    out = dict(blob)
    for field in _DICT_FIELDS:
        if field in out:
            out[field] = as_dict(out[field])
    for field in _LIST_FIELDS:
        if field in out:
            out[field] = as_list(out[field])

    cred = out.get("credibility")
    if isinstance(cred, dict) and cred:
        cred = dict(cred)
        if "overall" in cred:
            cred["overall"] = as_score(cred["overall"])
        recommendation = cred.get("recommendation")
        if recommendation is not None and not isinstance(recommendation, str):
            cred["recommendation"] = "manual_review"
        out["credibility"] = cred

    for field in ("summary", "one_liner", "file_name"):
        if field in out and not isinstance(out[field], str):
            out[field] = ""

    return out


def report_summary_row(report_id: str, blob: Any, fallback_file_name: str = "") -> dict:
    """
    The five fields every list, ranking and export needs, pulled out of a
    blob of any shape.
    """
    report = normalize_report(blob)
    cred = as_dict(report.get("credibility"))
    candidate = as_dict(report.get("candidate"))
    return {
        "id": report_id,
        "file_name": as_str(report.get("file_name")) or fallback_file_name,
        "candidate_name": as_str(candidate.get("name")) or "Unknown",
        "overall_score": as_score(cred.get("overall")),
        "recommendation": as_str(cred.get("recommendation")) or "manual_review",
    }
