"""
HireLens — Career trajectory metrics.

This module replaces the previous inline `talent_velocity` block in
`engine.py`, which did not compute anything about a candidate's career. It
was::

    velocity_score = max(50, min(98, 60 + (num_roles * 5) + (total_skills * 2)))
    "promotion_cadence_months": round(36 / max(num_roles, 1))
    "retention_stability_score": max(60, min(95, 100 - (num_roles * 4)))

Three problems with that, in order of severity:

1. It was presented to recruiters as a "Predictive Career Growth Index
   computed from skill acquisition rate and role trajectory" but read no
   dates, no tenures and no titles. A candidate with three roles and twenty
   listed skills scored 60 + 15 + 40 = 115, clamped to 98 — and so did a
   candidate with three roles and forty listed skills. In practice almost
   every resume with a normal skills section scored 98/100 "Accelerating",
   which is worse than useless: it is a confident-looking number that
   carries no information.
2. `36 / num_roles` is not a promotion cadence. It is a constant divided by
   a role count, so a candidate with more jobs mechanically looked like they
   were promoted faster.
3. `100 - num_roles * 4` penalised job count with no reference to how long
   the candidate actually stayed anywhere — the thing "retention stability"
   is supposed to measure.

What this module does instead: derives every number from the dates and
titles actually extracted from the resume, and returns an explicit
`insufficient_data` state when the resume does not carry enough parseable
dates to say anything. Refusing to answer is a valid output here — a blank
is more honest than a fabricated 98.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

logger = logging.getLogger("hirelens")

# Seniority is read from two independent parts of a title:
#
#   * a MODIFIER  — "junior", "senior", "staff", "principal", "head of" …
#   * a BASE noun — "engineer", "developer", "analyst", "manager" …
#
# They are matched separately because a modifier qualifies the base noun
# rather than competing with it. Taking the maximum over one flat list gets
# "Junior Developer" wrong: it matches both "junior" and "developer", and
# max() picks the base noun, ranking a junior identically to an unqualified
# engineer. When a modifier is present it therefore wins outright; the base
# noun only decides the rank when the title carries no modifier at all.
#
# Where a base noun is itself inherently senior ("director", "vp"), it lives
# in the modifier table, because that IS the seniority signal.

SENIORITY_MODIFIERS: list[tuple[int, tuple[str, ...]]] = [
    (1, ("intern", "internship", "trainee", "apprentice")),
    (2, ("junior", "jr", "associate", "graduate", "entry level", "assistant")),
    (4, ("senior", "sr", "lead", "supervisor")),
    (5, ("staff", "principal", "manager", "head")),
    (6, ("director", "architect", "senior manager", "vice president")),
    (7, ("vp", "svp", "evp", "chief", "cto", "cio", "ceo", "cfo", "coo", "founder", "co-founder", "partner")),
]

# Unqualified individual-contributor nouns. Rank 3 sits between "junior" and
# "senior", which is what an unmodified "Software Engineer" means.
SENIORITY_BASE: tuple[str, ...] = (
    "engineer", "developer", "programmer", "analyst", "designer",
    "consultant", "specialist", "scientist", "administrator", "researcher",
)

# Retained for callers that want to introspect the full ladder.
SENIORITY_LADDER: list[tuple[int, tuple[str, ...]]] = sorted(
    SENIORITY_MODIFIERS + [(3, SENIORITY_BASE)], key=lambda x: x[0]
)

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

_PRESENT = {"present", "current", "now", "ongoing", "today", "date"}


def parse_partial_date(value: Any, *, today: date | None = None) -> date | None:
    """
    Parse the loose date strings an LLM extracts from a resume.

    Handles ``2022-03``, ``2022/03``, ``March 2022``, ``Mar 2022``, ``2022``
    and the various spellings of "present". A bare year resolves to January,
    which is the conservative choice: it never invents tenure the resume
    doesn't claim.

    Returns ``None`` for anything unparseable rather than guessing.
    """
    if value is None:
        return None
    if isinstance(value, date):
        return value

    s = str(value).strip().lower()
    if not s or s in {"null", "none", "n/a", "-"}:
        return None
    if any(p in s for p in _PRESENT):
        return today or date.today()

    # 2022-03 / 2022/3 / 2022.03
    m = re.match(r"^(\d{4})[-/.](\d{1,2})", s)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12 and 1900 <= year <= 2100:
            return date(year, month, 1)

    # 03/2022 — month-first, distinguished from the above by field width
    m = re.match(r"^(\d{1,2})[-/.](\d{4})$", s)
    if m:
        month, year = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12 and 1900 <= year <= 2100:
            return date(year, month, 1)

    # "march 2022" / "mar 2022" / "mar. 2022"
    m = re.match(r"^([a-z]{3,9})\.?\s+(\d{4})$", s)
    if m and m.group(1)[:3] in _MONTHS:
        month = _MONTHS[m.group(1)[:4]] if m.group(1)[:4] in _MONTHS else _MONTHS[m.group(1)[:3]]
        year = int(m.group(2))
        if 1900 <= year <= 2100:
            return date(year, month, 1)

    # Bare year
    m = re.match(r"^(\d{4})$", s)
    if m:
        year = int(m.group(1))
        if 1900 <= year <= 2100:
            return date(year, 1, 1)

    return None


def months_between(start: date, end: date) -> int:
    """Whole months from `start` to `end`, floored at 0."""
    return max(0, (end.year - start.year) * 12 + (end.month - start.month))


def seniority_rank(title: Any) -> int | None:
    """
    Map a job title to a seniority rung, or None when the title carries no
    recognisable signal (in which case it contributes nothing to advancement
    counting rather than being guessed at).

    A modifier always beats the base noun, so "Junior Developer" ranks below
    "Software Engineer". Among modifiers the highest wins, so "Senior Staff
    Engineer" ranks as staff (5) rather than senior (4).
    """
    if not title:
        return None
    # Keep hyphens: "co-founder" and "vice-president" are single tokens.
    t = re.sub(r"[^a-z\s-]", " ", str(title).lower())
    padded = f" {' '.join(t.split())} "

    best: int | None = None
    for rank, keywords in SENIORITY_MODIFIERS:
        for kw in keywords:
            if f" {kw} " in padded:
                best = rank if best is None else max(best, rank)
    if best is not None:
        return best

    for kw in SENIORITY_BASE:
        if f" {kw} " in padded:
            return 3
    return None


def _role_timeline(experience: list[dict], today: date) -> list[dict]:
    """
    Build a chronologically sorted list of roles that have a parseable start
    date. Roles without one are dropped — they cannot contribute to any
    duration-based metric, and silently treating them as zero-length would
    understate tenure.
    """
    roles = []
    for e in experience:
        if not isinstance(e, dict):
            continue
        start = parse_partial_date(e.get("start_date"), today=today)
        if start is None:
            continue
        end_raw = e.get("end_date")
        end = parse_partial_date(end_raw, today=today) or today
        is_current = end >= today or (
            isinstance(end_raw, str) and any(p in end_raw.lower() for p in _PRESENT)
        )
        if end < start:
            # Transposed or misparsed dates — don't produce negative tenure.
            logger.debug("Dropping role with end before start: %s", e.get("role"))
            continue

        # Prefer an explicit duration_months from extraction when it is
        # consistent with the parsed dates; fall back to the date delta.
        derived = months_between(start, end)
        stated = e.get("duration_months")
        months = derived
        if isinstance(stated, (int, float)) and stated > 0:
            if abs(int(stated) - derived) <= 2:
                months = int(stated)

        roles.append({
            "role": e.get("role"),
            "company": e.get("company"),
            "start": start,
            "end": end,
            "months": months,
            "is_current": is_current,
            "rank": seniority_rank(e.get("role")),
        })

    roles.sort(key=lambda r: r["start"])
    return roles


def _band(value: float, bands: list[tuple[float, str]]) -> str:
    for threshold, label in bands:
        if value >= threshold:
            return label
    return bands[-1][1]


def compute_career_trajectory(
    experience: list[dict] | None,
    *,
    today: date | None = None,
) -> dict:
    """
    Derive career trajectory metrics from extracted work history.

    Every returned number is traceable to a date or title in the resume. When
    fewer than two roles carry a parseable start date, this returns
    ``{"status": "insufficient_data", ...}`` rather than a fabricated score —
    there is genuinely nothing to measure from a single undated role, and a
    number invented to fill the panel would be worse than an empty one.

    Returned keys when ``status == "computed"``:

    - ``total_experience_months``  — union of role spans, so overlapping or
      concurrent roles are not double-counted.
    - ``median_tenure_months``     — median of completed role tenures.
    - ``roles_analyzed``           — how many roles had usable dates.
    - ``advancement_steps``        — count of upward seniority transitions.
    - ``months_per_advancement``   — measured months of experience per
      upward step, or ``None`` when no advancement is observable.
    - ``gap_months``               — total months not covered by any role.
    - ``retention_stability``      — 0-100 from median tenure.
    - ``progression_score``        — 0-100 from advancement rate.
    - ``trajectory``               — a short label for the two above.
    - ``basis``                    — human-readable note on what was measured.
    """
    today = today or date.today()
    roles = _role_timeline(list(experience or []), today)

    if len(roles) < 2:
        return {
            "status": "insufficient_data",
            "roles_analyzed": len(roles),
            "reason": (
                "Career trajectory needs at least two roles with readable dates. "
                f"{len(roles)} of {len(experience or [])} role(s) on this resume had a "
                "start date this parser could read."
            ),
        }

    # ── Total experience as a union of intervals ─────────────────────────────
    # Summing role durations would double-count concurrent roles (a common
    # pattern for contractors and anyone with a side role).
    merged: list[list[date]] = []
    for r in roles:
        if merged and r["start"] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], r["end"])
        else:
            merged.append([r["start"], r["end"]])
    total_months = sum(months_between(s, e) for s, e in merged)

    # ── Gaps between the merged spans ────────────────────────────────────────
    gap_months = sum(
        months_between(merged[i][1], merged[i + 1][0]) for i in range(len(merged) - 1)
    )

    # ── Median tenure over completed roles ───────────────────────────────────
    # A current role's tenure is censored (still running), so including it
    # would drag the median down for anyone recently started.
    completed = sorted(r["months"] for r in roles if not r["is_current"])
    tenure_pool = completed or sorted(r["months"] for r in roles)
    mid = len(tenure_pool) // 2
    median_tenure = (
        tenure_pool[mid]
        if len(tenure_pool) % 2
        else (tenure_pool[mid - 1] + tenure_pool[mid]) // 2
    )

    # ── Advancement: count upward seniority transitions ──────────────────────
    ranked = [r["rank"] for r in roles if r["rank"] is not None]
    advancement_steps = sum(
        1 for a, b in zip(ranked, ranked[1:]) if b > a
    )
    months_per_advancement = (
        round(total_months / advancement_steps) if advancement_steps else None
    )

    # ── Scores ───────────────────────────────────────────────────────────────
    # Retention: median tenure of 24+ months is the top of the band. This is
    # a descriptive statistic, not a judgement — short tenure is normal in
    # some markets and the UI labels it as an observation.
    retention_stability = max(0, min(100, round((median_tenure / 24) * 100)))

    # Progression: an upward step roughly every 30 months of measured
    # experience is treated as a full score. Candidates with no title-based
    # advancement score 0 here, which is correct: none was observable.
    if months_per_advancement is None:
        progression_score = 0
    else:
        progression_score = max(0, min(100, round((30 / months_per_advancement) * 100)))

    if advancement_steps == 0:
        trajectory = "No title advancement observed"
    else:
        trajectory = _band(
            progression_score,
            [(80, "Fast advancement"), (50, "Steady advancement"), (0, "Gradual advancement")],
        )

    years = total_months / 12
    basis = (
        f"Measured from {len(roles)} dated role(s) spanning {years:.1f} years. "
        f"Median completed tenure {median_tenure} months; "
        + (
            f"{advancement_steps} upward title change(s)."
            if advancement_steps
            else "no upward title change detected."
        )
    )

    return {
        "status": "computed",
        "total_experience_months": total_months,
        "median_tenure_months": median_tenure,
        "roles_analyzed": len(roles),
        "advancement_steps": advancement_steps,
        "months_per_advancement": months_per_advancement,
        "gap_months": gap_months,
        "retention_stability": retention_stability,
        "progression_score": progression_score,
        "trajectory": trajectory,
        "basis": basis,
    }
