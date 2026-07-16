"""
HireLens — GitHub Skill Verification (Feature 3)

Calls the live GitHub public API (no scraping, no stored snapshots) to
cross-check a candidate's claimed skills against the languages actually
used in their public repositories.

Honesty notes surfaced to the recruiter in the response itself:
- Only PUBLIC repos are visible — strong private-repo work won't show up.
- Without a GITHUB_TOKEN, GitHub allows 60 unauthenticated requests/hour
  per server IP — fine for occasional single-candidate checks, but bulk
  verification will hit that fast. Set GITHUB_TOKEN (free) to raise it to
  5000/hour.
- This is a corroborating SIGNAL, not proof of authorship.
"""

import re
import logging
import httpx
from app.core.config import settings

logger = logging.getLogger("hirelens")

# Maps a GitHub-reported repo language to the skill-name family a resume
# would plausibly use for it (kept intentionally small + conservative).
LANGUAGE_ALIASES = {
    "c#": ["c#", "csharp", ".net", "dotnet"],
    "c++": ["c++", "cpp"],
    "shell": ["bash", "shell scripting", "shell"],
    "jupyter notebook": ["python", "data science", "machine learning"],
    "html": ["html", "html5"],
    "css": ["css", "css3"],
    "typescript": ["typescript", "ts"],
    "javascript": ["javascript", "js", "node", "node.js", "nodejs"],
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


def _skill_matches_language(skill: str, language: str) -> bool:
    skill_l, lang_l = skill.lower().strip(), language.lower().strip()
    if not skill_l or not lang_l:
        return False
    if skill_l == lang_l or skill_l in lang_l or lang_l in skill_l:
        return True
    for aliases in LANGUAGE_ALIASES.values():
        if lang_l in aliases and skill_l in aliases:
            return True
    return False


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
                params={"sort": "updated", "per_page": 30, "type": "owner"},
            )
            if repos_res.is_success:
                repos = repos_res.json()
        except httpx.HTTPError as e:
            logger.warning(f"GitHub repo list fetch failed for {username}: {e}")

        lang_counts: dict[str, int] = {}
        for repo in repos:
            lang = repo.get("language")
            if lang:
                lang_counts[lang] = lang_counts.get(lang, 0) + 1

        top_languages = sorted(lang_counts, key=lang_counts.get, reverse=True)[:10]

        verified, unverified = [], []
        for skill in claimed_skills:
            if any(_skill_matches_language(skill, lang) for lang in top_languages):
                verified.append(skill)
            else:
                unverified.append(skill)

        if verified:
            status = "verified"
        elif public_repos == 0:
            status = "no_public_activity"
        else:
            status = "partial"

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
            "note": (
                f"Cross-checked against {len(repos)} public repositories."
                if repos else
                "Account exists but has no accessible public repositories — "
                "private-only work won't show up here."
            ),
        }
