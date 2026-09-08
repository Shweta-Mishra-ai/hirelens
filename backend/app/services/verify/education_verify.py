"""
HireLens — Education Verification (Feature 3)

Cross-checks claimed institutions against the free, no-key Hipolabs
University Domains API (mirrors Hipo's global university/domain dataset).

Match-quality note: Hipolabs does substring matching against each
institution's CANONICAL registered name — a resume that says "IIT Delhi"
or "Delhi Technological University, Main Campus" often won't match on the
first try because the registry's actual name differs slightly. Rather than
giving up on one query, this module retries with progressively broader/
cleaned variants of the name before reporting "not found" — reusing the
same client/connection.

Honesty note: this is a best-effort registry lookup, not an official
degree-verification service (which would require paid partnerships like
the National Student Clearinghouse). A "not_found" result does NOT mean
the institution is fake — smaller, newer, or non-English-named institutions
are frequently just missing from this open dataset.
"""

import re
import logging
import httpx
from app.core.config import settings

logger = logging.getLogger("hirelens")

# HTTPS, deliberately — this was plain http://.
#
# This lookup is what turns into `status: "verified"` on a candidate's degree,
# which is one of the strongest claims this product makes. Deriving it from an
# unauthenticated, unencrypted response means anyone on the network path
# (hosting network, ISP, a spoofed DNS answer) can rewrite the response: forge
# a match so a fabricated university reads as verified, or blank it so a real
# one reads as unverifiable and drags the candidate's trust score down.
#
# There is deliberately NO http:// fallback. Silently downgrading on a TLS
# failure would give back exactly the property being fixed, at the moment an
# attacker is most likely to be interfering. A handshake failure surfaces as
# status "error" instead — see _search_once — which is honest: we could not
# check, rather than a verdict we cannot stand behind.
HIPOLABS_URL = "https://universities.hipolabs.com/search"
MAX_INSTITUTIONS = 8

# Common qualifiers that appear on resumes but not in an institution's
# canonical registry name — stripping these before a retry query
# significantly improves match rate without loosening the match itself
# (Hipolabs still does its own substring match on the cleaned term).
TRAILING_QUALIFIERS = re.compile(
    r"\s*[\(\[].*?[\)\]]\s*$"              # trailing "(Main Campus)" etc.
    r"|\s*[-–—,]\s*(main campus|campus|india|main|extension)\s*$",
    re.IGNORECASE,
)
KNOWN_ABBREVIATIONS = {
    "iit": "indian institute of technology",
    "nit": "national institute of technology",
    "iim": "indian institute of management",
    "iiit": "indian institute of information technology",
    "bits": "birla institute of technology",
    "mit": "massachusetts institute of technology",
}


def _candidate_queries(institution: str) -> list[str]:
    """Yields the raw name first, then progressively broader/cleaned variants."""
    queries = [institution]

    cleaned = TRAILING_QUALIFIERS.sub("", institution).strip()
    if cleaned and cleaned.lower() != institution.lower():
        queries.append(cleaned)

    # Expand a leading known abbreviation ("IIT Delhi" → "Indian Institute of Technology Delhi")
    first_word = institution.strip().split(" ", 1)[0].lower().rstrip(".")
    if first_word in KNOWN_ABBREVIATIONS:
        expanded = KNOWN_ABBREVIATIONS[first_word] + institution[len(first_word) + 1:]
        queries.append(expanded.strip())

    # Last resort: just the most distinctive (usually longest) word —
    # broad, but Hipolabs itself still requires a substring match so this
    # rarely over-matches in practice.
    words = [w for w in re.split(r"\s+", cleaned or institution) if len(w) > 3]
    if words:
        queries.append(max(words, key=len))

    # De-dupe while preserving order
    seen = set()
    out = []
    for q in queries:
        key = q.lower()
        if key and key not in seen:
            seen.add(key)
            out.append(q)
    return out[:4]  # cap retries per institution


async def _search_once(client: httpx.AsyncClient, query: str) -> list[dict] | None:
    try:
        r = await client.get(HIPOLABS_URL, params={"name": query})
    except httpx.HTTPError as e:
        logger.warning(f"University lookup failed for '{query}': {e}")
        return None
    if not r.is_success:
        return None
    return r.json() if r.content else []


async def verify_education(education: list[dict]) -> list[dict]:
    results: list[dict] = []
    if not education:
        return results

    async with httpx.AsyncClient(timeout=settings.VERIFY_TIMEOUT_SECONDS) as client:
        for edu in education[:MAX_INSTITUTIONS]:
            institution = (edu.get("institution") or "").strip() if isinstance(edu, dict) else str(edu).strip()

            if not institution:
                results.append({"institution": None, "status": "skipped", "note": "No institution name on resume."})
                continue

            matches = None
            matched_query = None
            had_error = False
            for query in _candidate_queries(institution):
                found = await _search_once(client, query)
                if found is None:
                    had_error = True
                    continue
                had_error = False
                if found:
                    matches = found
                    matched_query = query
                    break

            if matches:
                best = matches[0]
                result = {
                    "institution": institution,
                    "status": "verified",
                    "matched_name": best.get("name"),
                    "country": best.get("country"),
                    "domain": (best.get("domains") or [None])[0],
                }
                if matched_query and matched_query.lower() != institution.lower():
                    result["note"] = f"Matched via broadened search term \"{matched_query}\"."
                results.append(result)
            elif had_error:
                results.append({
                    "institution": institution, "status": "error",
                    "note": "Could not reach the university registry right now.",
                })
            else:
                results.append({
                    "institution": institution,
                    "status": "not_found",
                    "note": "Not in the open university registry after multiple search variants — this does NOT "
                            "necessarily mean it's fake; smaller, newer, or non-English-named institutions are "
                            "frequently just missing from this free dataset.",
                })

    return results
