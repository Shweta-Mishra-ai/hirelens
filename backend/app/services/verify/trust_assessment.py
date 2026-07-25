"""
HireLens — Trust Assessment (combined signal, rule-based)

Why rule-based and not another LLM call: the whole point of this feature is
to be the one output a recruiter can actually rely on. An LLM judging its
own AI-content-detection output would just be another probabilistic guess
stacked on the first one — if it's wrong, nobody can tell why. This module
is deliberately simple, deterministic, and fully auditable: every point
added or subtracted is logged in `reasoning`, so a recruiter (or a future
developer debugging a bad verdict) can see exactly why.

Core principle: TEXT is cheap to fake. REAL-WORLD EVIDENCE (a GitHub account
with actual commit history, a real institution) is expensive to fake. So
verified/not-verified evidence is weighted more heavily than the AI-content
writing-style signal, which is treated as a corroborating hint, not a verdict
on its own.
"""

from typing import Any


def compute_trust_assessment(
    ai_content_analysis: dict[str, Any] | None,
    verification: dict[str, Any] | None,
    overall_score: int,
) -> dict[str, Any]:
    """
    Returns:
      {
        "verdict": "high_confidence" | "moderate_confidence" | "low_confidence" | "insufficient_evidence",
        "score": -100..100  (signed — negative leans "concerning", positive leans "trustworthy")
        "reasoning": ["human-readable line per signal considered"],
        "evidence_available": bool  — whether ANY verification signal exists at all
      }
    """
    reasoning: list[str] = []
    points = 0
    evidence_available = False

    # ── AI-content writing-style signal (weak on its own — corroborating only) ──
    ai_content_analysis = ai_content_analysis or {}
    likelihood = ai_content_analysis.get("likelihood", "low")
    if likelihood == "high":
        points -= 15
        reasoning.append("Resume text shows multiple strong AI-generated-writing patterns (−15)")
    elif likelihood == "medium":
        points -= 6
        reasoning.append("Resume text shows some AI-writing patterns (−6)")
    else:
        reasoning.append("No strong AI-generated-writing signal in resume text (neutral)")

    # ── GitHub: real-world evidence, weighted heavily ──────────────────────
    gh = (verification or {}).get("github") or {}
    gh_status = gh.get("status")
    if gh_status == "verified":
        evidence_available = True
        n_verified = len(gh.get("verified_skills") or [])
        gain = min(30, 15 + n_verified * 3)
        points += gain
        reasoning.append(f"GitHub account verified with {n_verified} claimed skill(s) evidenced in real repos (+{gain})")
    elif gh_status == "partial":
        evidence_available = True
        points += 5
        reasoning.append("GitHub account exists but few claimed skills evidenced in public repos (+5)")
    elif gh_status == "not_found":
        evidence_available = True
        points -= 25
        reasoning.append("GitHub username on resume does not correspond to a real account (−25)")
    elif gh_status == "no_public_activity":
        evidence_available = True
        points -= 3
        reasoning.append("GitHub account exists but has no public repositories to check (−3, weak signal)")
    # no_username / rate_limited / error → not counted either way (no evidence, not a red flag)

    # ── Education: real-world evidence ──────────────────────────────────────
    edu_list = (verification or {}).get("education") or []
    verified_edu = [e for e in edu_list if e.get("status") == "verified"]
    not_found_edu = [e for e in edu_list if e.get("status") == "not_found"]
    if verified_edu:
        evidence_available = True
        points += 10
        reasoning.append(f"{len(verified_edu)} institution(s) confirmed in university registry (+10)")
    if not_found_edu and not verified_edu:
        evidence_available = True
        # Deliberately small penalty — registry coverage gaps are common and
        # this must never be the deciding factor on its own.
        points -= 5
        reasoning.append(
            f"{len(not_found_edu)} institution(s) not found in open registry (−5, weak signal — "
            "registry coverage is incomplete, this alone is not damning)"
        )

    # ── Credibility score itself (already a blended signal, light weight here) ──
    if overall_score >= 80:
        points += 8
    elif overall_score < 45:
        points -= 8

    points = max(-100, min(100, points))

    if not evidence_available:
        verdict = "insufficient_evidence"
    elif points >= 25:
        verdict = "high_confidence"
    elif points >= -10:
        verdict = "moderate_confidence"
    else:
        verdict = "low_confidence"

    return {
        "verdict": verdict,
        "score": points,
        "reasoning": reasoning,
        "evidence_available": evidence_available,
    }
