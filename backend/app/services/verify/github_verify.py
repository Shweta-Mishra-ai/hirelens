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

# Equivalence families. Every member of a family is treated as naming the
# same underlying skill, in either direction — so GitHub reporting the
# language "Dockerfile" satisfies a resume claiming "Docker", and vice versa.
#
# Each family must list EVERY spelling including the GitHub-reported one.
# The previous version keyed families by the GitHub name but omitted that
# name from its own alias list, so the alias path never actually fired;
# "Dockerfile" only matched "Docker" through the substring fallback that
# `_skill_matches_evidence` has since dropped.
SKILL_FAMILIES: list[set[str]] = [
    {"c#", "csharp", "c sharp", ".net", "dotnet", "asp.net"},
    {"c++", "cpp", "cplusplus"},
    {"shell", "bash", "sh", "zsh", "shell script", "shell scripting"},
    {"jupyter notebook", "jupyter", "ipython"},
    {"html", "html5"},
    {"css", "css3", "scss", "sass", "less"},
    {"typescript", "ts"},
    {"javascript", "js", "ecmascript"},
    {"node", "node.js", "nodejs"},
    {"dockerfile", "docker", "containerization", "containers"},
    {"kubernetes", "k8s", "kubectl"},
    {"tensorflow", "tf", "keras"},
    {"pytorch", "torch"},
    {"postgresql", "postgres", "plpgsql", "psql"},
    {"objective-c", "objectivec", "objc"},
    {"golang", "go"},
    {"ruby", "rb"},
    {"rust", "rs"},
    {"python", "py"},
    {"markdown", "md"},
    {"jinja", "jinja2"},
    {"vue", "vue.js", "vuejs"},
    {"react", "react.js", "reactjs"},
]

# Precomputed lookup: normalized name -> the family it belongs to.
_FAMILY_INDEX: dict[str, set[str]] = {}
for _family in SKILL_FAMILIES:
    for _member in _family:
        _FAMILY_INDEX[_member] = _family

# Skills whose names are too short or too common to ever be matched by
# anything other than an exact token. Without this, substring or fuzzy
# matching credits "R" from "Rust", "Go" from "Google", "C" from "CSS",
# and "AI" from "domain".
AMBIGUOUS_SHORT_SKILLS = {"r", "c", "go", "d", "ai", "ml", "js", "ts", "sh", "rb", "py", "tf"}

# Ordinary prose that appears in repo descriptions and is not a technology.
# Repo *topics* are not filtered — those are deliberately chosen labels.
_DESCRIPTION_STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "from", "into", "your", "you",
    "are", "was", "will", "can", "all", "any", "how", "why", "what", "when",
    "simple", "small", "basic", "easy", "fast", "new", "old", "using", "used",
    "use", "build", "built", "building", "make", "makes", "made", "tool",
    "tools", "app", "application", "project", "repo", "repository", "demo",
    "example", "examples", "sample", "test", "tests", "code", "source",
    "library", "framework", "based", "written", "implementation", "implements",
    "support", "supports", "management", "manage", "manager", "system",
    "service", "services", "server", "client", "personal", "awesome", "list",
    "collection", "set", "very", "more", "most", "some", "not", "but", "its",
    "has", "have", "been", "one", "two", "first", "best", "free", "open",
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


def _normalize(text: str) -> str:
    """
    Lowercase, collapse whitespace, and drop surrounding punctuation.

    Leading dots are preserved: ".net" is a skill name, and stripping the dot
    turns it into "net", which belongs to no family and matches nothing.
    """
    cleaned = re.sub(r"\s+", " ", text.lower().strip())
    cleaned = cleaned.lstrip("(['\"“‘ ")
    return cleaned.rstrip(".,;:!?)]}'\"”’ ")


def _tokens(text: str) -> set[str]:
    """
    Split a phrase into comparable tokens, preserving the characters that
    actually distinguish language names: `c++` and `c#` must not both
    collapse to `c`, and `node.js` must survive as one token.
    """
    return {t for t in re.split(r"[\s/,|]+", _normalize(text)) if t}


def _skill_matches_evidence(skill: str, evidence_terms: set[str]) -> bool:
    """
    Decide whether a claimed skill is evidenced by GitHub activity.

    This used to accept a match whenever either string contained the other:

        if skill_l == term_l or skill_l in term_l or term_l in skill_l:

    which made the check actively misleading rather than merely noisy.
    "Java" was verified by a JavaScript repo. "R" matched "Rust", "React"
    and "Terraform". "Go" matched "Google", "MongoDB" and "Django". "C"
    matched essentially any evidence term. Because a false "verified" tells
    a recruiter a claim has been independently corroborated when it has
    not, these errors are worse than reporting nothing.

    A skill now matches only when one of the following holds:

      1. it equals an evidence term exactly (normalized), or
      2. it and the term belong to the same equivalence family, or
      3. it appears as a whole token inside a multi-word term — and only
         when the skill is long enough and not on the ambiguous list.

    Everything else is reported as unverified, which the UI already frames
    as "not seen in public repos" rather than as a mark against the
    candidate.
    """
    skill_n = _normalize(skill)
    if not skill_n:
        return False

    skill_family = _FAMILY_INDEX.get(skill_n)
    skill_is_ambiguous = skill_n in AMBIGUOUS_SHORT_SKILLS

    for term in evidence_terms:
        term_n = _normalize(term)
        if not term_n:
            continue

        # 1. Exact match.
        if skill_n == term_n:
            return True

        # 2. Same equivalence family (bidirectional).
        term_family = _FAMILY_INDEX.get(term_n)
        if skill_family is not None and skill_family is term_family:
            return True

        # 3. Whole-token containment, e.g. skill "kubernetes" evidenced by
        #    the topic "kubernetes operator". Never for ambiguous short
        #    names, and never as a bare substring.
        if skill_is_ambiguous or len(skill_n) < 3:
            continue

        term_tokens = _tokens(term_n)
        if skill_n in term_tokens:
            return True
        if skill_family is not None and skill_family & term_tokens:
            return True

        # A multi-word skill ("machine learning") evidenced by a term that
        # contains that exact phrase as consecutive words.
        if " " in skill_n and re.search(rf"\b{re.escape(skill_n)}\b", term_n):
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
                # Topics are curated by the repo owner and are strong signal.
                evidence_terms.add(topic.replace("-", " "))

            # Description words are much weaker: every ordinary English word
            # in a sentence lands here too. Dropping common prose words keeps
            # a description like "a simple tool to manage builds" from
            # contributing "simple", "tool" and "manage" as if they were
            # technologies.
            desc = repo.get("description") or ""
            for word in re.findall(r"[A-Za-z][A-Za-z0-9+.#-]{1,}", desc):
                lowered = word.lower()
                if lowered not in _DESCRIPTION_STOPWORDS:
                    evidence_terms.add(lowered)

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
