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

HIPOLABS_URL = "http://universities.hipolabs.com/search"
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


def _candidate_queries(institution: str) -> list[tuple[str, bool]]:
    """
    The raw name first, then progressively broader variants, each tagged with
    whether a hit on it is strong enough to call the institution confirmed.

    The tag is the important part. Searching the full name, or the same name
    with "(Main Campus)" trimmed, or a known abbreviation expanded, all still
    describe the institution the resume claimed. Searching a single word out of
    it does not — and the registry does substring matching, so "Technical" from
    "Stanford Technical College" comes back with "Technical University of
    Munich" and every word of that response is true and irrelevant.
    """
    queries: list[tuple[str, bool]] = [(institution, True)]

    cleaned = TRAILING_QUALIFIERS.sub("", institution).strip()
    if cleaned and cleaned.lower() != institution.lower():
        queries.append((cleaned, True))

    # Expand a leading known abbreviation ("IIT Delhi" → "Indian Institute of Technology Delhi").
    #
    # Split on the word, rather than slicing by its length: "IIT" is three
    # characters but "IIT." is four, and slicing past the wrong offset joined
    # the expansion straight onto the rest of the name — "indian institute of
    # technologyDelhi", a query that matches nothing in the registry.
    parts = institution.strip().split(None, 1)
    first_word = parts[0].lower().rstrip(".") if parts else ""
    if first_word in KNOWN_ABBREVIATIONS:
        remainder = parts[1].strip() if len(parts) > 1 else ""
        expanded = f"{KNOWN_ABBREVIATIONS[first_word]} {remainder}".strip()
        queries.append((expanded, True))

    # Last resort: the most distinctive (usually longest) word. Useful for
    # finding a plausible candidate to show the recruiter, never enough on its
    # own to confirm one.
    words = [w for w in re.split(r"\s+", cleaned or institution) if len(w) > 3]
    if words:
        queries.append((max(words, key=len), False))

    seen = set()
    out: list[tuple[str, bool]] = []
    for q, strong in queries:
        key = q.lower()
        if key and key not in seen:
            seen.add(key)
            out.append((q, strong))
    return out[:4]  # cap retries per institution


# Grammar, not identity. Dropping these changes nothing about which
# institution is being named.
_STOPWORDS = {"of", "the", "and", "at", "for", "main", "campus", "a"}

# Words describing what kind of institution it is. These are NOT noise —
# "Springfield State College" and "Springfield University" are different
# places — so they must match like any other word. They are listed only
# because a name made of nothing else ("The University") identifies nobody.
_INSTITUTION_TYPES = {
    "university", "universite", "universidad", "universitat", "college",
    "institute", "institution", "school", "academy", "polytechnic",
}


def _tokens(name: str) -> set[str]:
    # Apostrophes are closed up rather than split on, so "Xavier's" and
    # "Xaviers" are the same word — registries drop the punctuation, resumes
    # keep it, and neither spelling means a different institution.
    flattened = re.sub(r"['\u2018\u2019]", "", (name or "").lower())
    return {t for t in re.split(r"[^a-z0-9]+", flattened) if t}


def _names_agree(claimed: str, matched: str) -> bool:
    """
    Whether the registry's name is really the institution the resume named.

    Every word of the claim, bar pure grammar, has to appear in the match. The
    registry answers a substring search, so without this a claim keeps whatever
    name the search happened to land on — and the report then tells a recruiter
    a different, real institution was confirmed.

    Deliberately one-directional: the registry's canonical name is often longer
    than the resume's ("Massachusetts Institute of Technology" for "MIT"), and
    that extra detail is not a disagreement. Extra words in the *claim* are.
    """
    claim_tokens = _tokens(claimed) - _STOPWORDS
    matched_tokens = _tokens(matched)

    # A name with no word of its own — "The University" — matches thousands of
    # entries and identifies none of them.
    if not (claim_tokens - _INSTITUTION_TYPES):
        return False

    return claim_tokens <= matched_tokens


def _best_match(matches: list[dict], claimed: str) -> dict:
    """The closest name in the response, rather than whichever came first."""
    from difflib import SequenceMatcher

    def score(row: dict) -> float:
        return SequenceMatcher(None, claimed.lower(), (row.get("name") or "").lower()).ratio()

    return max(matches, key=score)


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
            query_is_strong = False
            had_error = False
            for query, strong in _candidate_queries(institution):
                found = await _search_once(client, query)
                if found is None:
                    had_error = True
                    continue
                had_error = False
                if found:
                    matches = found
                    matched_query = query
                    query_is_strong = strong
                    break

            if matches:
                best = _best_match(matches, institution)
                matched_name = best.get("name") or ""

                # Two independent gates, and a match has to clear both. The
                # search term must have described the whole institution, and
                # the name that came back must actually be the one searched
                # for.
                #
                # Checked against the QUERY, not the raw claim. A strong query
                # is the claim restated — trimmed of "(Main Campus)", or with a
                # known abbreviation spelled out — and "IIT Delhi" shares no
                # word with "Indian Institute of Technology Delhi" even though
                # they are the same place. The weak single-word query never
                # reaches here as confirmed, so it cannot exploit this.
                confirmed = query_is_strong and _names_agree(matched_query or institution, matched_name)

                result = {
                    "institution": institution,
                    "status": "verified" if confirmed else "possible_match",
                    "matched_name": matched_name,
                    "country": best.get("country"),
                    "domain": (best.get("domains") or [None])[0],
                }
                if confirmed:
                    if matched_query and matched_query.lower() != institution.lower():
                        result["note"] = (
                            f"Matched via search term \"{matched_query}\". Confirms this "
                            f"institution is in the registry — not that the candidate attended it."
                        )
                    else:
                        result["note"] = (
                            "Found in the open university registry. This confirms the "
                            "institution exists, not that the candidate attended it."
                        )
                else:
                    result["note"] = (
                        f"The closest entry in the registry is \"{matched_name}\", which is not "
                        f"clearly the same institution as \"{institution}\". Treated as unconfirmed "
                        f"— worth a look, not evidence either way."
                    )
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
