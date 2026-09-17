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
from app.services.verify.ssrf_guard import is_public_http_url

logger = logging.getLogger("hirelens")

URL_RE = re.compile(r"https?://[^\s,;)]+", re.IGNORECASE)
MAX_CERTS = 10
MAX_REDIRECT_HOPS = 3


def _extract_url(text: str) -> str | None:
    m = URL_RE.search(text)
    return m.group(0).rstrip(".") if m else None


# Markup, scripts and styles, stripped before the page is searched for a name.
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

# Pages that answer "no such credential" still return 200 and still contain
# whatever was in the URL. Seeing one of these means the link did not confirm
# anything, whatever else is on the page.
_NEGATIVE_MARKERS = (
    "not found",
    "no certificate",
    "no credential",
    "no record",
    "no such",
    "no longer valid",
    "invalid credential",
    "invalid certificate",
    "has been revoked",
    "no results",
    "does not exist",
    "expired credential",
    "could not be verified",
    "unable to verify",
)


def _visible_text(html_source: str) -> str:
    """
    The words a person would read, without the markup around them.

    Searching the raw response instead would match a name inside a URL, a
    meta tag, a JSON blob or a script variable — including the URL that was
    just requested, which on many credential sites contains the name being
    looked for. That is a check that confirms itself.
    """
    without_code = _SCRIPT_STYLE_RE.sub(" ", html_source or "")
    without_tags = _TAG_RE.sub(" ", without_code)
    return _WHITESPACE_RE.sub(" ", without_tags).strip().lower()


def _name_parts(candidate_name: str) -> list[str]:
    parts = [p for p in re.split(r"[^A-Za-z]+", candidate_name or "") if len(p) >= 2]
    return [p.lower() for p in parts]


def _name_on_page(candidate_name: str, page_text: str) -> bool:
    """
    Whether this candidate's name really appears on the page.

    Every part of the name has to be there, each as a whole word. A plain
    substring test on a short or common name matches almost any page —
    "Li" inside "Link" and "Client", "An" inside "Announcement" — and turns a
    credential page that was never about this candidate into a confirmation.
    """
    parts = _name_parts(candidate_name)
    # A single short token is not enough to identify anyone.
    if len(parts) < 2 and not (parts and len(parts[0]) >= 6):
        return False
    return all(
        re.search(rf"(?<![a-z]){re.escape(part)}(?![a-z])", page_text) for part in parts
    )


async def _safe_fetch(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    """GET with manual redirect handling — re-validates SSRF safety on every
    hop, since a URL that's safe can still redirect to an internal address."""
    current_url = url
    for _ in range(MAX_REDIRECT_HOPS + 1):
        if not is_public_http_url(current_url):
            logger.warning(f"Blocked unsafe/internal URL during cert verification: {current_url}")
            return None
        try:
            r = await client.get(current_url, follow_redirects=False)
        except httpx.HTTPError as e:
            logger.warning(f"Certification link unreachable: {current_url} — {e}")
            return None
        if r.is_redirect:
            next_url = r.headers.get("location")
            if not next_url:
                return r
            current_url = str(httpx.URL(current_url).join(next_url))
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

            page_text = _visible_text(r.text)
            says_not_found = any(marker in page_text for marker in _NEGATIVE_MARKERS)
            name_found = _name_on_page(candidate_name, page_text)

            if says_not_found:
                results.append({
                    "name": name,
                    "url": url,
                    "status": "link_reachable_name_not_confirmed",
                    "note": "The page loaded but reports no such credential. Worth asking about.",
                })
            elif name_found:
                results.append({
                    "name": name,
                    "url": url,
                    "status": "verified_via_link",
                    "note": None,
                })
            elif not _name_parts(candidate_name):
                results.append({
                    "name": name,
                    "url": url,
                    "status": "link_reachable_name_not_confirmed",
                    "note": "The link works, but no candidate name was extracted from the "
                            "resume to check it against.",
                })
            else:
                results.append({
                    "name": name,
                    "url": url,
                    "status": "link_reachable_name_not_confirmed",
                    "note": "The link works, but the candidate's name wasn't found on the page.",
                })

    return results
