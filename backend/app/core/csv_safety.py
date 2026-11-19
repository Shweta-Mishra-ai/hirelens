"""
CSV export safety.

Every CSV this API produces carries text that came from somewhere other than
the recruiter: candidate names are read out of an uploaded resume by a model,
file names are whatever the uploader called the file. Spreadsheet programs
treat a cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return as
a formula. A resume whose name line reads `=HYPERLINK("https://evil", "Open")`
therefore becomes a live link in the recruiter's Excel the moment they open
the export, and older Excel builds would run DDE payloads the same way.

Prefixing such a cell with a single quote makes the spreadsheet show it as
text. Numbers are left alone: a score of -1 is a number, not a formula.
"""

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value):
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def safe_row(values) -> list:
    return [safe_cell(v) for v in values]
