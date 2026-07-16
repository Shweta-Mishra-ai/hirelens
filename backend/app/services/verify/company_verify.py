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


async def verify_experience_companies(experience: list[dict]) -> list[dict]:
    results: list[dict] = []
    if not experience:
        return results

    async with httpx.AsyncClient(timeout=settings.VERIFY_TIMEOUT_SECONDS, follow_redirects=True) as client:
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
                try:
                    r = await client.head(candidate_url, follow_redirects=True)
                    if r.status_code < 400:
                        found = True
                        break
                except httpx.HTTPError:
                    continue

            results.append({
                "company": company,
                "domain_checked": domain,
                "status": "domain_found" if found else "domain_not_found",
                "note": (
                    None if found else
                    "No website found at the guessed domain — false negatives are common here "
                    "(unregistered businesses, non-.com domains, rebrands). This is a weak signal only."
                ),
            })

    return results
