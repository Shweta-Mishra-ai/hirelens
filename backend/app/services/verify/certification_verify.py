"""
HireLens — Certification Verification (Feature 3)

HireLens's current resume extraction stores certifications as plain
strings (e.g. "AWS Certified Solutions Architect"), matching what most
resumes actually contain — no dedicated verify-link field yet. This
module still adds real value in two ways:

1. If a candidate DID paste a public verify link inline in the cert text
   (common with Credly/Coursera/Credential.net badges, e.g.
   "AWS Certified — https://credly.com/badges/abc123"), we extract and
   live-fetch it, checking whether the candidate's name appears on the page.
2. Otherwise we're explicit that public verification isn't possible from
   resume text alone — this is a data-availability limitation, not a
   fraud signal, and is reported as such.
"""

import re
import logging
import httpx
from app.core.config import settings
from app.services.verify.ssrf_guard import is_public_http_url, safe_fetch

logger = logging.getLogger("hirelens")

URL_RE = re.compile(r"https?://[^\s,;)]+", re.IGNORECASE)
MAX_CERTS = 10
MAX_REDIRECT_HOPS = 3


def _extract_url(text: str) -> str | None:
    m = URL_RE.search(text)
    return m.group(0).rstrip(".") if m else None


async def _safe_fetch(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    """GET with manual redirect handling — re-validates SSRF safety on every
    hop (a URL that's safe can still redirect to an internal address), and
    pins each hop's DNS resolution to the exact IP just validated (see
    safe_fetch() in ssrf_guard.py) so there's no gap between checking a
    hostname and connecting to it for an attacker's DNS to land a
    different answer in."""
    current_url = url
    for _ in range(MAX_REDIRECT_HOPS + 1):
        try:
            r = await safe_fetch(client, current_url)
        except ValueError:
            logger.warning(f"Blocked unsafe/internal URL during cert verification: {current_url}")
            return None
        except httpx.HTTPError as e:
            logger.warning(f"Certification link unreachable: {current_url} — {e}")
            return None
        if r.is_redirect:
            next_url = r.headers.get("location")
            if not next_url:
                return r
            current_url = httpx.URL(current_url).join(next_url).human_repr()
            continue
        return r
    return None  # too many redirects


async def verify_certifications(certifications: list, candidate_name: str | None) -> list[dict]:
    results: list[dict] = []
    if not certifications:
        return results

    async with httpx.AsyncClient(timeout=settings.VERIFY_TIMEOUT_SECONDS) as client:
        for cert in certifications[:MAX_CERTS]:
            raw = cert if isinstance(cert, str) else str(cert.get("name", cert))
            url = _extract_url(raw)
            name = URL_RE.sub("", raw).strip(" -–—:") or raw

            if not url:
                results.append({
                    "name": name, "status": "no_link_provided",
                    "note": "No public verification link found in the resume text for this certification.",
                })
                continue

            if not is_public_http_url(url):
                results.append({
                    "name": name, "url": url, "status": "link_unreachable",
                    "note": "This link points to a non-public address and was not fetched for safety reasons.",
                })
                continue

            r = await _safe_fetch(client, url)
            if r is None:
                results.append({"name": name, "url": url, "status": "link_unreachable"})
                continue

            if not r.is_success:
                results.append({"name": name, "url": url, "status": "link_unreachable", "note": f"Returned {r.status_code}."})
                continue

            page_text = r.text.lower()
            name_found = bool(candidate_name) and candidate_name.strip().lower() in page_text

            results.append({
                "name": name,
                "url": url,
                "status": "verified_via_link" if name_found else "link_reachable_name_not_confirmed",
                "note": None if name_found else "The link works, but the candidate's name wasn't found on the page.",
            })

    return results
