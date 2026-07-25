"""
HireLens — GitHub Skill Verification (Feature 3)

Calls the live GitHub public API (no scraping, no stored snapshots) to
cross-check a candidate's claimed skills against evidence in their public
repositories: full language breakdown per repo (not just the single
"primary language" GitHub shows in a repo list), repo topics, and repo
descriptions.

Why the language breakdown matters: GitHub's repo-list endpoint only
returns ONE "primary" language per repo (whichever has the most bytes).
A Python + Docker + Terraform project would show up as just "Python" —
silently hiding real, evidenced skills. The /languages endpoint per repo
returns the full byte-count breakdown, so a candidate who claims Docker
or SQL can actually be checked properly, not just their single dominant
language per project.

Honesty notes surfaced to the recruiter in the response itself:
- Only PUBLIC repos are visible — strong private-repo work won't show up.
- Without a GITHUB_TOKEN, GitHub allows 60 unauthenticated requests/hour
  per server IP. The full per-repo language breakdown costs one extra
  request per repo scanned, so without a token we scan fewer repos to
  stay within budget. Set GITHUB_TOKEN (free) to raise the limit to
  5000/hour AND scan significantly more repos per candidate.
- This is a corroborating SIGNAL, not proof of authorship.
"""

import re
import asyncio
import logging
import httpx
from app.core.config import settings

logger = logging.getLogger("hirelens")

REPOS_TO_LIST = 100          # how many repos to list (GitHub's per_page max)
DEEP_SCAN_WITH_TOKEN = 25    # repos to fetch full language breakdown for, with GITHUB_TOKEN
DEEP_SCAN_NO_TOKEN = 8       # same, but conservative without a token (60/hr budget)
DEEP_SCAN_CONCURRENCY = 5    # parallel /languages requests

# Maps a GitHub-reported language/topic to the skill-name family a resume
# would plausibly use for it (kept intentionally small + conservative).
SKILL_ALIASES = {
    "c#": ["c#", "csharp", ".net", "dotnet"],
    "c++": ["c++", "cpp"],
    "shell": ["bash", "shell scripting", "shell", "shell script"],
    "jupyter notebook": ["python", "data science", "machine learning", "jupyter"],
    "html": ["html", "html5"],
    "css": ["css", "css3", "scss", "sass"],
    "typescript": ["typescript", "ts"],
    "javascript": ["javascript", "js", "node", "node.js", "nodejs"],
    "dockerfile": ["docker", "containerization", "containers"],
    "kubernetes": ["k8s", "kubernetes"],
    "tensorflow": ["tensorflow", "deep learning", "machine learning", "ml"],
    "pytorch": ["pytorch", "deep learning", "machine learning", "ml"],
    "postgresql": ["postgres", "postgresql", "sql"],
    "plpgsql": ["postgres", "postgresql", "sql"],
}


def extract_username(github_field: str | None) -> str | None:
    """Pulls a GitHub username out of a URL or accepts a bare username."""
    if not github_field:
        return None
    field = github_field.strip()
    m = re.search(r"github\.com/([A-Za-z0-9\-]{1,39})", field, re.IGNORECASE)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9\-]{1,39}", field):
        return field
    return None


def _skill_matches_evidence(skill: str, evidence_terms: set[str]) -> bool:
    skill_l = skill.lower().strip()
    if not skill_l:
        return False
    for term in evidence_terms:
        term_l = term.lower().strip()
        if not term_l:
            continue
        if skill_l == term_l or skill_l in term_l or term_l in skill_l:
            return True
        for aliases in SKILL_ALIASES.values():
            if term_l in aliases and skill_l in aliases:
                return True
    return False


async def _fetch_repo_languages(client: httpx.AsyncClient, owner: str, repo: str, sem: asyncio.Semaphore) -> dict:
    async with sem:
        try:
            r = await client.get(f"https://api.github.com/repos/{owner}/{repo}/languages")
            if r.is_success:
                return r.json()  # {"Python": 45231, "Dockerfile": 812, ...}
        except httpx.HTTPError as e:
            logger.warning(f"Language fetch failed for {owner}/{repo}: {e}")
        return {}


async def verify_github(username: str | None, claimed_skills: list[str]) -> dict:
    """Real-time GitHub lookup. Never raises — always returns a status dict."""
    if not username:
        return {
            "status": "no_username",
            "username": None,
            "note": "No GitHub username found on the resume or provided by the recruiter.",
        }

    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

    async with httpx.AsyncClient(timeout=settings.VERIFY_TIMEOUT_SECONDS, headers=headers) as client:
        try:
            profile_res = await client.get(f"https://api.github.com/users/{username}")
        except httpx.HTTPError as e:
            logger.warning(f"GitHub profile fetch failed for {username}: {e}")
            return {"status": "error", "username": username, "note": "Could not reach GitHub right now."}

        if profile_res.status_code == 404:
            return {
                "status": "not_found", "username": username,
                "note": "No GitHub account exists with this username.",
            }
        if profile_res.status_code == 403:
            return {
                "status": "rate_limited", "username": username,
                "note": "GitHub API rate limit hit. Set GITHUB_TOKEN in your backend .env to raise the limit from 60/hr to 5000/hr.",
            }
        if not profile_res.is_success:
            return {"status": "error", "username": username, "note": f"GitHub API returned {profile_res.status_code}."}

        profile = profile_res.json()
        public_repos = int(profile.get("public_repos") or 0)

        repos: list[dict] = []
        try:
            repos_res = await client.get(
                f"https://api.github.com/users/{username}/repos",
                params={"sort": "updated", "per_page": REPOS_TO_LIST, "type": "owner"},
            )
            if repos_res.is_success:
                repos = repos_res.json()
        except httpx.HTTPError as e:
            logger.warning(f"GitHub repo list fetch failed for {username}: {e}")

        # ── Evidence collection ────────────────────────────────────────────
        # 1. Repo topics + description (free — already in the list response)
        evidence_terms: set[str] = set()
        for repo in repos:
            for topic in (repo.get("topics") or []):
                evidence_terms.add(topic.replace("-", " "))
            desc = repo.get("description") or ""
            evidence_terms.update(w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9+.#]{2,}", desc))

        # 2. Full per-repo language breakdown (costs 1 request per repo scanned —
        #    scan depth depends on whether GITHUB_TOKEN raised our budget)
        deep_scan_limit = DEEP_SCAN_WITH_TOKEN if settings.GITHUB_TOKEN else DEEP_SCAN_NO_TOKEN
        scan_targets = [r for r in repos if not r.get("fork")][:deep_scan_limit]

        lang_bytes: dict[str, int] = {}
        if scan_targets:
            sem = asyncio.Semaphore(DEEP_SCAN_CONCURRENCY)
            results = await asyncio.gather(*(
                _fetch_repo_languages(client, username, r["name"], sem) for r in scan_targets
            ))
            for lang_map in results:
                for lang, byte_count in lang_map.items():
                    lang_bytes[lang] = lang_bytes.get(lang, 0) + byte_count
                    evidence_terms.add(lang.lower())

        # Fallback: if we didn't deep-scan everything, still credit the
        # primary `language` field GitHub reports on repos we skipped —
        # better a coarse signal than none for the long tail.
        for repo in repos[len(scan_targets):]:
            lang = repo.get("language")
            if lang:
                evidence_terms.add(lang.lower())

        top_languages = sorted(lang_bytes, key=lang_bytes.get, reverse=True)[:10]

        verified, unverified = [], []
        for skill in claimed_skills:
            if _skill_matches_evidence(skill, evidence_terms):
                verified.append(skill)
            else:
                unverified.append(skill)

        if verified:
            status = "verified"
        elif public_repos == 0:
            status = "no_public_activity"
        else:
            status = "partial"

        scanned_note = (
            f"Cross-checked {len(scan_targets)} repos in full detail (all languages + topics)"
            + (f", plus {len(repos) - len(scan_targets)} more by primary language only." if len(repos) > len(scan_targets) else ".")
        ) if repos else "Account exists but has no accessible public repositories — private-only work won't show up here."

        return {
            "status": status,
            "username": username,
            "profile_url": profile.get("html_url"),
            "avatar_url": profile.get("avatar_url"),
            "public_repos": public_repos,
            "account_created": profile.get("created_at"),
            "top_languages": top_languages,
            "verified_skills": sorted(set(verified)),
            "unverified_skills": sorted(set(unverified)),
            "note": scanned_note,
        }
