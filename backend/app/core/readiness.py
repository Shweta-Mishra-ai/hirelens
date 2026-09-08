"""
HireLens — Production configuration readiness checks.

Every check here answers one question: "if this is wrong, does the app look
broken to a real user while the process itself stays perfectly healthy?"

That class of failure is what actually bites on launch day. The service boots,
Render's health check goes green, the logs look calm — and every request from
the real frontend fails in the browser, or every account created that day
evaporates on the next redeploy. Two startup guards already exist in main.py
for the cases severe enough to refuse to boot (a default SECRET_KEY, a
wildcard CORS origin). The checks below are the ones where refusing to boot
would be worse than running, because the operator needs a reachable /health
endpoint to diagnose them at all.

Collected in one place, and surfaced BOTH in the boot log and in
GET /api/v1/health, so "is this deploy actually configured?" has an answer
that does not require shell access to the container.
"""

from app.core.config import settings

DEFAULT_SECRET_KEY = "dev-secret-key-change-in-production-min-32"

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "[::1]")


def _is_local_origin(origin: str) -> bool:
    o = origin.strip().lower()
    return any(f"//{h}" in o or o.startswith(h) for h in _LOCAL_HOSTS)


def config_warnings() -> list[dict]:
    """Production misconfigurations that leave the process healthy but the
    product broken. Returns [] outside production, and in a healthy deploy.

    Each entry: {"code", "message"} — `code` is stable and safe to alert on.
    """
    if not settings.is_production:
        return []

    warnings: list[dict] = []

    # ── CORS ────────────────────────────────────────────────────────────────
    # render.yaml declares ALLOWED_ORIGINS as `sync: false`, meaning the
    # operator has to type it into the Render dashboard by hand. Forget to,
    # and it silently keeps the "http://localhost:3000" default — so the
    # browser blocks every single request from the deployed frontend as a
    # CORS violation. The API is fine, the health check is green, and the
    # product is 100% unusable with only a console error to go on. This is
    # the single most likely launch-day failure after Supabase.
    origins = settings.allowed_origins_list
    cors_is_localhost_only = all(_is_local_origin(o) for o in origins)
    if cors_is_localhost_only:
        warnings.append({
            "code": "cors_localhost_only",
            "message": (
                f"ALLOWED_ORIGINS is {origins!r} — localhost only, in production. "
                "Every request from the deployed frontend will be blocked by the "
                "browser as a CORS violation while this API itself looks healthy. "
                "Set ALLOWED_ORIGINS to your real frontend origin(s), e.g. "
                "'https://your-app.vercel.app'."
            ),
        })

    # ── Storage durability ──────────────────────────────────────────────────
    # Also logged at boot in main.py; repeated here so it shows up in /health
    # alongside everything else rather than only in a scrolled-past log line.
    if not (settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY):
        warnings.append({
            "code": "storage_ephemeral",
            "message": (
                "SUPABASE_URL/SUPABASE_SERVICE_KEY are unset. Accounts and reports "
                "go to local SQLite / process memory, both wiped on every restart, "
                "redeploy and idle spin-down. Users will lose their logins and data."
            ),
        })

    # ── LLM ─────────────────────────────────────────────────────────────────
    # Resume analysis is the entire product. Without a key the upload flow
    # accepts files and then fails on every one of them.
    if not (settings.GEMINI_API_KEY or settings.GROQ_API_KEY or settings.ANTHROPIC_API_KEY):
        warnings.append({
            "code": "llm_unconfigured",
            "message": (
                "No LLM API key is set (GEMINI_API_KEY / GROQ_API_KEY / "
                "ANTHROPIC_API_KEY). Resume analysis — the core feature — will "
                "fail for every upload."
            ),
        })

    # ── Frontend URL ────────────────────────────────────────────────────────
    # Used to build team-invite and password-reset links that get emailed to
    # real people. Left at the default, those links point at whatever domain
    # happens to be baked in rather than this deployment's frontend.
    if _is_local_origin(settings.FRONTEND_URL):
        warnings.append({
            "code": "frontend_url_local",
            "message": (
                f"FRONTEND_URL is {settings.FRONTEND_URL!r} in production. Team "
                "invite and password-reset emails will contain links pointing at "
                "localhost, which no recipient can open."
            ),
        })
    elif (
        origins
        and not cors_is_localhost_only
        and settings.FRONTEND_URL.rstrip("/") not in [o.rstrip("/") for o in origins]
    ):
        warnings.append({
            "code": "frontend_url_not_in_cors",
            "message": (
                f"FRONTEND_URL ({settings.FRONTEND_URL}) is not listed in "
                f"ALLOWED_ORIGINS ({origins}). Emailed invite/reset links will land "
                "on a frontend whose API calls the browser then blocks as CORS "
                "violations. These two settings should agree."
            ),
        })

    # ── Email delivery ──────────────────────────────────────────────────────
    # Candidate notifications and team invites silently no-op without a
    # transport. The UI still reports the action as done.
    if not (
        settings.RESEND_API_KEY
        or (settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD)
    ):
        warnings.append({
            "code": "email_unconfigured",
            "message": (
                "No email transport configured (RESEND_API_KEY, or SMTP_HOST + "
                "SMTP_USER + SMTP_PASSWORD). Candidate notifications and team "
                "invites will not be delivered — send_raw_email() returns False "
                "for every send."
            ),
        })

    return warnings
