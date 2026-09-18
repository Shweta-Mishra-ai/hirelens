"""
HireLens — Employer Verification (Feature 3)

Domain-check only (no OpenCorporates lookup — kept out per product
decision to stay simple/fast on the free tier). We guess a plausible
`.com` domain from the company name and check whether it responds.

Honesty note: this is a heuristic, not a registry lookup. It will
false-negative on: unregistered/informal businesses, companies that use
a non-`.com` TLD, rebranded companies, and multi-word names that don't
map cleanly to a domain. Reported as a "weak signal", never as a red flag.
"""

import re
import logging
import httpx
from app.core.config import settings
from app.services.verify.ssrf_guard import is_public_http_url

logger = logging.getLogger("hirelens")

STOPWORDS = {
    "inc", "llc", "ltd", "corp", "corporation", "company", "co", "group",
    "technologies", "technology", "tech", "solutions", "systems", "labs",
    "pvt", "private", "limited", "the", "and", "&",
}
MAX_COMPANIES = 10


def _guess_domain(company: str) -> str | None:
    cleaned = re.sub(r"[^a-zA-Z0-9 ]", "", company or "").lower()
    words = [w for w in cleaned.split() if w not in STOPWORDS]
    if not words:
        return None
    return "".join(words) + ".com"


# Redirect hops allowed before giving up on a candidate URL — matches the
# limit used in certification_verify.py and ats.py for consistency.
_MAX_REDIRECT_HOPS = 3


async def _safe_head(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    """
    HEAD request that re-validates the SSRF guard on every redirect hop.

    The company domain here is guessed from the candidate's resume text
    (via _guess_domain), which makes it indirectly attacker-influenced the
    same way a directly-supplied URL would be. With follow_redirects=True the
    guard would only ever see the guessed domain, and httpx would follow the
    rest of the chain unchecked — including a hop ending at an internal or
    metadata address. Mirrors the per-hop re-check used elsewhere here.
    """
    current_url = url
    for _ in range(_MAX_REDIRECT_HOPS + 1):
        if not is_public_http_url(current_url):
            return None
        try:
            r = await client.head(current_url, follow_redirects=False)
        except httpx.HTTPError:
            return None
        if r.is_redirect:
            location = r.headers.get("location")
            if not location:
                return None
            current_url = str(httpx.URL(current_url).join(location))
            continue
        return r
    return None


async def verify_experience_companies(experience: list[dict]) -> list[dict]:
    results: list[dict] = []
    if not experience:
        return results

    # NOTE: follow_redirects is intentionally NOT set to True on this
    # client (it defaults to False) — every actual request goes through
    # _safe_head() above, which handles redirects itself with a guard
    # re-check on each hop.
    async with httpx.AsyncClient(timeout=settings.VERIFY_TIMEOUT_SECONDS) as client:
        for exp in experience[:MAX_COMPANIES]:
            company = (exp.get("company") or "").strip() if isinstance(exp, dict) else ""
            if not company:
                results.append({"company": None, "status": "skipped"})
                continue

            domain = _guess_domain(company)
            if not domain:
                results.append({
                    "company": company, "status": "skipped",
                    "note": "Could not derive a checkable domain from this company name.",
                })
                continue

            found = False
            for scheme in ("https://", "http://"):
                candidate_url = f"{scheme}{domain}"
                if not is_public_http_url(candidate_url):
                    continue
                r = await _safe_head(client, candidate_url)
                if r is not None and r.status_code < 400:
                    found = True
                    break

            results.append({
                "company": company,
                "domain_checked": domain,
                "status": "domain_found" if found else "domain_not_found",
                "note": (
                    # Said out loud on the positive case too. A live website at
                    # a guessed domain shows the employer is real; it is not
                    # evidence the candidate worked there, and a green row with
                    # no caveat beside an employment claim reads as though it is.
                    "A live website answers at this domain, so the employer appears real. "
                    "This does not confirm the candidate worked there."
                    if found else
                    "No website found at the guessed domain — false negatives are common here "
                    "(unregistered businesses, non-.com domains, rebrands). This is a weak signal only."
                ),
            })

    return results
