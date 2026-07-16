"""
HireLens — Education Verification (Feature 3)

Cross-checks claimed institutions against the free, no-key Hipolabs
University Domains API (mirrors Hipo's global university/domain dataset).

Honesty note: this is a best-effort registry lookup, not an official
degree-verification service (which would require paid partnerships like
the National Student Clearinghouse). A "not_found" result does NOT mean
the institution is fake — smaller or newly-founded institutions may
simply be missing from the open dataset.
"""

import logging
import httpx
from app.core.config import settings

logger = logging.getLogger("hirelens")

HIPOLABS_URL = "http://universities.hipolabs.com/search"
MAX_INSTITUTIONS = 8


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

            try:
                r = await client.get(HIPOLABS_URL, params={"name": institution})
            except httpx.HTTPError as e:
                logger.warning(f"University lookup failed for '{institution}': {e}")
                results.append({
                    "institution": institution, "status": "error",
                    "note": "Could not reach the university registry right now.",
                })
                continue

            if not r.is_success:
                results.append({
                    "institution": institution, "status": "error",
                    "note": f"University registry returned {r.status_code}.",
                })
                continue

            matches = r.json() if r.content else []
            if matches:
                best = matches[0]
                results.append({
                    "institution": institution,
                    "status": "verified",
                    "matched_name": best.get("name"),
                    "country": best.get("country"),
                    "domain": (best.get("domains") or [None])[0],
                })
            else:
                results.append({
                    "institution": institution,
                    "status": "not_found",
                    "note": "Not in the open university registry — this does NOT necessarily mean it's fake; "
                            "smaller or newly-founded institutions are often missing from the dataset.",
                })

    return results
