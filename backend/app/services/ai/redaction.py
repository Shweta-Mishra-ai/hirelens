"""
Remove contact details from resume text before it reaches an AI provider,
and put them back afterwards.

Why: on the Gemini API's free tier, Google's terms allow submitted content to
be used to improve its products, including review by people. A resume is a
candidate's personal data. The analysis needs the work and education history
— not the candidate's email address, phone number, profile links or name — so
those are replaced with placeholders such as [[EMAIL_1]] before any prompt is
built, and restored in the finished report on this server. Contact details,
candidate emails and GitHub verification keep working; the provider never
sees them.

What it does not do: it cannot remove every identifying detail. Employers,
dates and institutions stay, because the analysis is about them. A name is
only redacted when it can be recognised as the resume's heading line.
"""

import re
from dataclasses import dataclass, field

_EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w-])")

# Links: anything with a scheme or www., plus bare profile hosts people write
# without one ("linkedin.com/in/anita").
_URL = re.compile(
    r"(?:https?://|www\.)[^\s<>()\[\]{}\"'|,;]+"
    r"|(?<![\w@.])(?:[a-z0-9-]+\.)*(?:linkedin\.com|github\.com|gitlab\.com|bitbucket\.org|"
    r"behance\.net|dribbble\.com|medium\.com|stackoverflow\.com|kaggle\.com|leetcode\.com)"
    r"/[^\s<>()\[\]{}\"'|,;]+",
    re.IGNORECASE,
)

# Candidate phone numbers: a run of digits with the usual separators. Every
# match is then checked by _is_phone, because the same shape also describes
# date ranges ("2019 - 2024", "01.2019 - 03.2021") that the timeline analysis
# depends on.
_PHONE = re.compile(r"(?<![\w+])\+?\(?\d[\d\s().-]{7,}\d(?!\w)")

_HEADING_STOPWORDS = {
    "resume", "résumé", "curriculum", "vitae", "cv", "profile", "summary",
    "contact", "objective", "experience", "education", "skills", "page",
}

_PLACEHOLDER = re.compile(
    r"\[\[\s*(EMAIL|PHONE|URL)_(\d+)\s*\]\]|\[\[\s*CANDIDATE_NAME\s*\]\]"
    r"|\b(EMAIL|PHONE|URL)_(\d+)\b|\bCANDIDATE_NAME\b"
)


def _is_phone(candidate: str) -> bool:
    groups = re.findall(r"\d+", candidate)
    digits = sum(len(g) for g in groups)
    if not 10 <= digits <= 15:
        return False
    # Every group a year or a one/two-digit day or month: a date, not a phone.
    if all((len(g) == 4 and g[:2] in ("19", "20")) or len(g) <= 2 for g in groups):
        return False
    return True


def _heading_name(text: str) -> str | None:
    """
    The candidate's name, if the resume opens with one.

    Resumes almost always lead with the name on a line of its own. Only that
    line is considered, and only when it reads like a name: two to four
    words, letters only, each capitalised. Anything else is left alone rather
    than guessed at.
    """
    for line in text.splitlines()[:4]:
        line = line.strip().strip("|•·-–— ").strip()
        if not line:
            continue
        words = line.split()
        if not 2 <= len(words) <= 4:
            return None
        cleaned = []
        for word in words:
            core = word.strip(".,")
            if not core or not all(ch.isalpha() or ch in "'-." for ch in core):
                return None
            if not core[0].isupper() or core.lower() in _HEADING_STOPWORDS:
                return None
            cleaned.append(core)
        return " ".join(cleaned)
    return None


@dataclass
class Redaction:
    text: str
    values: dict[str, str] = field(default_factory=dict)

    def restore(self, data):
        """Put the original values back into any JSON-like structure."""
        if not self.values:
            return data
        if isinstance(data, str):
            return _PLACEHOLDER.sub(self._lookup, data)
        if isinstance(data, list):
            return [self.restore(item) for item in data]
        if isinstance(data, dict):
            return {key: self.restore(value) for key, value in data.items()}
        return data

    def _lookup(self, match: re.Match) -> str:
        kind = match.group(1) or match.group(3)
        number = match.group(2) or match.group(4)
        key = f"{kind}_{number}" if kind else "CANDIDATE_NAME"
        return self.values.get(key, match.group(0))


def redact(text: str) -> Redaction:
    values: dict[str, str] = {}
    seen: dict[tuple[str, str], str] = {}

    def keep(kind: str, original: str) -> str:
        normal = original.strip().lower()
        if (kind, normal) not in seen:
            key = f"{kind}_{sum(1 for k, _ in seen if k == kind) + 1}"
            seen[(kind, normal)] = key
            values[key] = original.strip()
        return f"[[{seen[(kind, normal)]}]]"

    # Emails before links, so "mailto:" and addresses inside links are
    # treated as what they are.
    out = _EMAIL.sub(lambda m: keep("EMAIL", m.group(0)), text)
    out = _URL.sub(lambda m: keep("URL", m.group(0).rstrip(".")) + ("." if m.group(0).endswith(".") else ""), out)
    out = _PHONE.sub(lambda m: keep("PHONE", m.group(0)) if _is_phone(m.group(0)) else m.group(0), out)

    name = _heading_name(text)
    if name:
        values["CANDIDATE_NAME"] = name
        out = re.sub(
            r"(?<!\w)" + r"\s+".join(re.escape(part) for part in name.split()) + r"(?!\w)",
            "[[CANDIDATE_NAME]]",
            out,
            flags=re.IGNORECASE,
        )

    return Redaction(text=out, values=values)
