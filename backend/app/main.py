"""HireLens API — Production FastAPI Application"""

from contextlib import asynccontextmanager
import asyncio, os, time, uuid, logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.body_limit import BodySizeLimitMiddleware
from app.core.exceptions import (
    HireLensException, RateLimitExceeded,
    FileTooLarge, UnsupportedFileType, AuthError, QuotaExceeded,
)
from app.api.v1.endpoints import analysis, reports, auth, health, bulk, match, verify, ats, teams, collaboration, copilot, jds, billing

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hirelens")

# HTTP client libraries log every request line — full URL included — at INFO.
# Any provider that authenticates with a query parameter would have its key
# written to the platform log on every call, and the request lines are noise
# besides. Warnings and errors still come through.
for _noisy in ("httpx", "httpx2", "httpcore", "hpack"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)




# ── Self-ping keep-alive (prevents Render free tier sleep) ──────────────────
#
# Render's free plan spins an instance down after roughly 15 minutes without
# traffic. Ten minutes leaves margin for one ping to fail without the gap
# reaching that window.
KEEP_ALIVE_SECONDS = 600
# Let startup finish before the first self-ping.
KEEP_ALIVE_STARTUP_DELAY = 30

async def _keep_alive_loop():
    """
    Pings our own /api/v1/health endpoint every 10 minutes so Render never
    considers the service idle and spins it down.
    Only runs in production; development can skip it.

    Requires BACKEND_URL to be set explicitly, and skips with a warning when
    it is not. Deriving it from FRONTEND_URL would mean guessing, and a
    keep-alive that pings the wrong host looks exactly like one that works.
    """
    import httpx

    backend_url = settings.BACKEND_URL.strip().strip('"').strip("'")
    if not backend_url:
        logger.warning(
            "Keep-alive pinger not started: BACKEND_URL is not set. "
            "Without it this service idle-sleeps on Render's free tier, and "
            "the first request afterwards takes 30-60s while the container "
            "wakes — which reads as the app being down. Set BACKEND_URL to "
            "this service's own public URL, e.g. "
            "https://your-service.onrender.com"
        )
        return

    # A keep-alive that pings the wrong place is worse than none: it logs
    # success forever while the service sleeps anyway.
    if "//" not in backend_url:
        backend_url = f"https://{backend_url}"
    if "localhost" in backend_url or "127.0.0.1" in backend_url:
        logger.error(
            "Keep-alive not started: BACKEND_URL is %s, a local address. "
            "The ping has to leave and re-enter through the public URL to "
            "count as traffic; pinging localhost keeps nothing awake.",
            backend_url,
        )
        return

    await asyncio.sleep(KEEP_ALIVE_STARTUP_DELAY)
    ping_url = backend_url.rstrip("/") + "/api/v1/health"
    logger.info("Keep-alive pinging %s every %ss", ping_url, KEEP_ALIVE_SECONDS)

    consecutive_failures = 0
    while True:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(ping_url)
            if r.status_code >= 400:
                raise RuntimeError(f"unexpected status {r.status_code}")
            if consecutive_failures:
                logger.info(
                    "Keep-alive ping recovered after %d failure(s)",
                    consecutive_failures,
                )
            consecutive_failures = 0
            logger.info(f"Keep-alive ping → {ping_url} [{r.status_code}]")
        except Exception as e:
            consecutive_failures += 1
            # Escalated, because a quietly failing keep-alive is
            # indistinguishable from a working one until the app is asleep
            # and someone reports that it is down.
            log = logger.critical if consecutive_failures >= 3 else logger.warning
            log(
                "Keep-alive ping to %s failed (%d in a row): %s%s",
                ping_url,
                consecutive_failures,
                e,
                " — this service will idle-sleep. Check that BACKEND_URL is "
                "this service's own public URL."
                if consecutive_failures >= 3
                else "",
            )
        await asyncio.sleep(KEEP_ALIVE_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"HireLens API starting — env={settings.APP_ENV}")

    # ── Security startup checks ─────────────────────────────────────────────
    # These raise SystemExit rather than just logging, deliberately. A log
    # line at startup is easy to miss in a deploy pipeline; a process that
    # refuses to boot is not. Forgeable JWTs and wide-open CORS are not
    # conditions this app should ever silently serve traffic under.
    if settings.is_production:
        # There is no longer a shipped default to compare against — an unset
        # key is simply empty here, because development fills its own in from
        # a machine-local file and production is left to fail.
        if len(settings.SECRET_KEY) < 32:
            logger.critical(
                "SECURITY: SECRET_KEY is unset or too short in production. "
                "Session tokens are signed with it, so a guessable value means "
                "anyone can mint one. Set a real random SECRET_KEY (32+ chars) "
                "in your environment immediately — e.g. "
                "`python -c \"import secrets; print(secrets.token_urlsafe(48))\"`."
            )
            raise SystemExit(
                "Refusing to start: SECRET_KEY is missing or too short for a "
                "production environment. Set SECRET_KEY (32+ chars) and redeploy."
            )
        if "*" in settings.allowed_origins_list:
            logger.critical(
                "SECURITY: ALLOWED_ORIGINS includes '*' in production — this allows "
                "any website to make authenticated requests to this API. Restrict it "
                "to your actual frontend domain(s)."
            )
            raise SystemExit(
                "Refusing to start: ALLOWED_ORIGINS is '*' in a production "
                "environment. Set it to your real frontend domain(s) and redeploy."
            )

        # A warning, not a refusal: the API works perfectly with only localhost
        # allowed, it just cannot be reached from the deployed site. The browser
        # blocks those requests before they are sent, so this surfaces as
        # "login does not work" with a completely healthy API and nothing in
        # these logs — the request never arrives to be logged.
        origins = settings.allowed_origins_list
        if origins and all(
            "localhost" in o or "127.0.0.1" in o for o in origins
        ):
            logger.warning(
                "ALLOWED_ORIGINS is %s — only local addresses. A deployed "
                "frontend will be blocked by the browser before its requests "
                "reach this API, which looks like sign-in being broken while "
                "every health check here passes. Add the site's origin, e.g. "
                "ALLOWED_ORIGINS=https://your-app.vercel.app",
                origins,
            )

        # Not a refusal — running on the local store is a legitimate choice for
        # a demo. It is a disaster silently, though: on Render's free plan the
        # container filesystem is ephemeral, so /app/data/local.db is destroyed
        # on every deploy AND every wake from idle sleep. Accounts created
        # yesterday are simply gone, which the person experiences as sign-in
        # having stopped working for no reason.
        if not (settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY):
            logger.critical(
                "No Supabase configured in production — accounts and reports "
                "are being written to a local SQLite file. On an ephemeral "
                "container filesystem (Render's free plan, any redeploy) that "
                "file is destroyed without warning, taking every account with "
                "it: users who signed up successfully can no longer sign in. "
                "Set SUPABASE_URL and SUPABASE_SERVICE_KEY, or attach a "
                "persistent disk, before taking real users."
            )

        # Links in invite and password-reset emails are built from
        # FRONTEND_URL. Its default is one particular deployment's address,
        # so any other deployment that leaves it unset sends its users'
        # reset links to someone else's site.
        if "FRONTEND_URL" not in settings.model_fields_set:
            logger.critical(
                "FRONTEND_URL is not set — invite and password-reset emails "
                "will link to the built-in default %s. Set FRONTEND_URL to this "
                "deployment's frontend origin.",
                settings.FRONTEND_URL,
            )

        # Resend refuses mail from a domain the account has not verified. The
        # default sender is not a domain this deployment owns, so every email
        # would be rejected — logged as a warning per send, easy to miss.
        if settings.RESEND_API_KEY and "SMTP_FROM_EMAIL" not in settings.model_fields_set:
            logger.critical(
                "RESEND_API_KEY is set but SMTP_FROM_EMAIL is not — mail would be "
                "sent from the default %s, which Resend rejects unless that "
                "domain is verified on your account. Set SMTP_FROM_EMAIL to an "
                "address on a domain you have verified with Resend.",
                settings.SMTP_FROM_EMAIL,
            )

        if not settings.admin_emails:
            logger.warning(
                "ADMIN_EMAILS is not set — operator endpoints (diagnostics, "
                "account stats, plan changes) are disabled in production."
            )

        # Render's free web services cannot open outbound connections on
        # ports 25, 465 or 587, so SMTP there fails on every send — after a
        # 10-second timeout each, which a recruiter sees as a hung button.
        # Paid Render instances can use SMTP, so this is a warning naming the
        # condition rather than a refusal; Resend (HTTPS) works on either.
        if (
            os.environ.get("RENDER") == "true"
            and settings.SMTP_HOST
            and not settings.RESEND_API_KEY
            and int(settings.SMTP_PORT) in (25, 465, 587)
        ):
            logger.warning(
                "Email is configured through SMTP (%s:%s) on Render. Render's FREE "
                "instances block ports 25, 465 and 587, so on the free plan every "
                "email will time out. Use RESEND_API_KEY instead, or ignore this "
                "on a paid instance.",
                settings.SMTP_HOST,
                settings.SMTP_PORT,
            )

        # Gemini's free tier may use submitted content to improve Google's
        # products. Redaction removes contact details, but resumes still go
        # there first unless the order says otherwise.
        first_provider = (settings.LLM_PROVIDER_ORDER or "gemini").split(",")[0].strip().lower()
        if first_provider == "gemini" and settings.GEMINI_API_KEY and settings.GROQ_API_KEY:
            logger.info(
                "Resumes go to Gemini first (LLM_PROVIDER_ORDER=%s). On Gemini's free "
                "tier Google may use them to improve its products; set "
                "LLM_PROVIDER_ORDER=groq,gemini,anthropic to send them to Groq first. "
                "See docs/DEPLOYMENT.md, 'Candidate data and free AI tiers'.",
                settings.LLM_PROVIDER_ORDER,
            )

        logger.info(
            "Config: origins=%s frontend=%s supabase=%s redis=%s",
            origins,
            settings.FRONTEND_URL,
            "set" if settings.SUPABASE_URL else "unset",
            "set" if settings.REDIS_URL else "unset",
        )

    # ── Worker/job-store consistency check ──────────────────────────────────
    # See the comment in Dockerfile above the uvicorn CMD for the full
    # explanation. This is a best-effort runtime check (uvicorn doesn't
    # expose --workers to the app process directly), so it checks the one
    # thing the app *can* see: whether Redis is configured. It cannot detect
    # "someone raised --workers without setting Redis" by itself — that's
    # why the Dockerfile comment is the primary defense — but it does catch
    # the single most common misconfiguration (Redis unset, multi-worker
    # intent signaled via WEB_CONCURRENCY, which Render sets automatically
    # on some plans).
    web_concurrency = os.environ.get("WEB_CONCURRENCY", "").strip()
    if web_concurrency and web_concurrency != "1" and not settings.REDIS_URL:
        logger.critical(
            f"SECURITY/CORRECTNESS: WEB_CONCURRENCY={web_concurrency} is set but "
            f"REDIS_URL is not configured. With more than one worker process and "
            f"no Redis, job status and report reads will randomly fail depending "
            f"on which worker handles the request — see job_store.py's docstring. "
            f"Set REDIS_URL, or set WEB_CONCURRENCY=1."
        )

    # Start keep-alive pinger in production
    _keep_alive_task = None
    if settings.is_production:
        _keep_alive_task = asyncio.create_task(_keep_alive_loop())
        logger.info("Keep-alive self-ping task started (every 10 min)")

    # ── Database schema check ───────────────────────────────────────────────
    # Migrations are run by hand, so new code can easily meet an old schema —
    # and the app degrades quietly when it does (plan limits stop being
    # enforced, for one). Checked off the startup path so a slow Supabase
    # never delays the port opening; the result is logged, CRITICAL if a
    # migration is missing, and served on /health.
    async def _check_schema() -> None:
        from app.core import schema_check
        from app.core.dependencies import get_db
        try:
            db = await asyncio.to_thread(get_db)
            if db is None:
                return
            report = await asyncio.to_thread(schema_check.cached, db, 0)
            schema_check.log_report(report)
        except Exception as e:  # never take the process down over a check
            logger.warning(f"Schema check could not run: {e}")

    _schema_task = None
    if settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY:
        _schema_task = asyncio.create_task(_check_schema())

    yield

    if _schema_task and not _schema_task.done():
        _schema_task.cancel()
    if _keep_alive_task:
        _keep_alive_task.cancel()
    logger.info("HireLens API shutting down")


# The interactive docs publish every route, parameter and schema to anyone who
# asks. Useful on a laptop; in production they are reconnaissance for free.
_docs_enabled = not settings.is_production

app = FastAPI(
    title="HireLens API",
    description="AI-powered recruiter decision intelligence.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

# ── Middleware ────────────────────────────────────────────────────────────────
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

@app.middleware("http")
async def request_middleware(request: Request, call_next):
    rid = str(uuid.uuid4())[:8]
    request.state.request_id = rid
    t0 = time.monotonic()
    try:
        response = await call_next(request)
        ms = (time.monotonic() - t0) * 1000
        response.headers["X-Request-ID"] = rid
        response.headers["X-Response-Time"] = f"{ms:.0f}ms"
        logger.info(f"{request.method} {request.url.path} → {response.status_code} ({ms:.0f}ms)")
        return response
    except Exception as e:
        ms = (time.monotonic() - t0) * 1000
        logger.error(f"Unhandled error {request.url.path} ({ms:.0f}ms): {e}", exc_info=True)
        return JSONResponse(status_code=500, content={
            "error": "internal_error",
            "message": "Unexpected error. Please try again.",
            "request_id": rid,
        })

# Body size limit: inside CORS (so a 413 is readable by the browser), outside
# everything that parses a body.
app.add_middleware(BodySizeLimitMiddleware)

# CORS is added LAST so it ends up OUTERMOST: Starlette wraps each new
# middleware around the ones already added, and the catch-all handler above
# has to run INSIDE the CORS layer. Outside it, a 500 goes back without an
# Access-Control-Allow-Origin header and the browser refuses to let the app
# read it — which leaves the frontend unable to tell a server error from an
# unreachable API: no status, no message, just a failed fetch. Everything the
# server says, "something went wrong" included, has to be readable by the app
# that asked.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Response-Time"],
)


# ── Exception Handlers ────────────────────────────────────────────────────────
def _request_id(request: Request) -> str:
    """The per-request trace id, or a placeholder if the middleware never ran."""
    return getattr(request.state, "request_id", "unknown")


# Field names as a person would say them, for validation messages. Anything
# not listed falls back to the raw field with underscores replaced.
_FIELD_LABELS = {
    "email": "Email",
    "password": "Password",
    "full_name": "Full name",
    "company": "Company",
    "name": "Name",
    "file": "File",
    "files": "Files",
    "jd_text": "Job description",
    "comment": "Comment",
    "vote": "Vote",
    "decision": "Decision",
}


def _humanize_validation_errors(errors: list) -> str:
    """
    Flatten Pydantic's error list into one sentence a user can act on.

    FastAPI's default 422 body is `{"detail": [{"loc": [...], "msg": ...}]}`,
    which is not the `{error, message, request_id}` envelope every other
    response uses and every client here expects. Clients were left either
    showing "Server error 422" or reaching into `detail` themselves.
    """
    parts: list[str] = []
    for err in errors[:5]:
        if not isinstance(err, dict):
            continue
        msg = str(err.get("msg") or "").strip()
        if not msg:
            continue
        # Pydantic prefixes custom validator messages with "Value error, ".
        if msg.lower().startswith("value error,"):
            msg = msg.split(",", 1)[1].strip()
        if msg == "Field required":
            msg = "is required"

        loc = [str(x) for x in (err.get("loc") or []) if x not in ("body", "query", "path")]
        field = loc[-1] if loc else ""
        if field and not field.isdigit():
            label = _FIELD_LABELS.get(field, field.replace("_", " ").capitalize())
            parts.append(f"{label} {msg}" if msg.startswith("is ") else f"{label}: {msg}")
        else:
            parts.append(msg)

    if not parts:
        return "Some of the submitted values were not valid."
    joined = ". ".join(p.rstrip(".") for p in parts)
    return f"{joined}."


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    """
    Return request-validation failures in the standard envelope.

    `details` is preserved for programmatic clients that want per-field
    information, but `message` is always present and always readable.
    """
    errors = exc.errors()
    logger.info(f"Validation failed on {request.method} {request.url.path}: {errors[:3]}")
    return JSONResponse(status_code=422, content={
        "error": "validation_error",
        "message": _humanize_validation_errors(errors),
        "request_id": _request_id(request),
        "details": [
            {
                "field": ".".join(
                    str(x) for x in (e.get("loc") or []) if x not in ("body", "query", "path")
                ),
                "message": str(e.get("msg") or ""),
            }
            for e in errors[:10]
            if isinstance(e, dict)
        ],
    })


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """
    Envelope for everything Starlette raises directly — chiefly 404 for an
    unknown route and 405 for a wrong method. Those come out of Starlette as
    `{"detail": "..."}`, and this puts them in the same shape as every other
    error the API returns, so the client has one thing to parse.
    """
    codes = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        413: "payload_too_large",
        415: "unsupported_media_type",
        429: "rate_limit_exceeded",
    }
    messages = {
        404: "That endpoint does not exist. Check the URL and the API version prefix.",
        405: f"{request.method} is not allowed on this endpoint.",
        413: "That request body is too large.",
    }
    detail = exc.detail if isinstance(exc.detail, str) else None
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": codes.get(exc.status_code, "http_error"),
            "message": messages.get(exc.status_code) or detail or "That request could not be completed.",
            "request_id": _request_id(request),
        },
        headers=getattr(exc, "headers", None) or None,
    )


@app.exception_handler(HireLensException)
async def hirelens_handler(request: Request, exc: HireLensException):
    return JSONResponse(status_code=exc.http_status, content={
        "error": exc.code, "message": exc.message, "request_id": _request_id(request),
    })

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={
        "error": "rate_limit_exceeded",
        "message": f"Too many requests. Retry after {exc.retry_after}s.",
        "retry_after": exc.retry_after,
        "request_id": _request_id(request),
    }, headers={"Retry-After": str(exc.retry_after)})

@app.exception_handler(FileTooLarge)
async def file_too_large_handler(request: Request, exc: FileTooLarge):
    return JSONResponse(status_code=413, content={
        "error": "file_too_large",
        "message": f"File exceeds {exc.max_mb}MB limit.",
        "max_mb": exc.max_mb,
        "request_id": _request_id(request),
    })

@app.exception_handler(UnsupportedFileType)
async def unsupported_type_handler(request: Request, exc: UnsupportedFileType):
    return JSONResponse(status_code=415, content={
        "error": "unsupported_file_type",
        "message": f"'{exc.file_type}' not supported. Upload PDF or DOCX.",
        "request_id": _request_id(request),
    })

def _upgrade_link() -> str | None:
    from app.services.billing import upgrade_link
    return upgrade_link()


@app.exception_handler(QuotaExceeded)
async def quota_handler(request: Request, exc: QuotaExceeded):
    return JSONResponse(status_code=402, content={
        "error": "quota_exceeded",
        "message": exc.message,
        "plan": exc.plan,
        "limit": exc.limit,
        "remaining": exc.remaining,
        "upgrade_url": _upgrade_link(),
        "request_id": _request_id(request),
    })


@app.exception_handler(AuthError)
async def auth_handler(request: Request, exc: AuthError):
    return JSONResponse(status_code=401, content={
        "error": "unauthorized",
        "message": exc.message,
        "request_id": _request_id(request),
    }, headers={"WWW-Authenticate": "Bearer"})

# ── Routes ────────────────────────────────────────────────────────────────────
app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(analysis.router, prefix="/api/v1/analysis", tags=["Analysis"])
app.include_router(bulk.router, prefix="/api/v1/bulk", tags=["Bulk Upload"])
app.include_router(match.router, prefix="/api/v1/match", tags=["JD Match"])
app.include_router(jds.router, prefix="/api/v1/job-descriptions", tags=["Saved JDs"])
app.include_router(verify.router, prefix="/api/v1/verify", tags=["Verification"])
app.include_router(ats.router, prefix="/api/v1/ats", tags=["ATS Import"])
app.include_router(teams.router, prefix="/api/v1/teams", tags=["Teams"])
app.include_router(billing.router, prefix="/api/v1/billing", tags=["Billing"])
app.include_router(reports.router, prefix="/api/v1/reports", tags=["Reports"])
app.include_router(collaboration.router, prefix="/api/v1/reports", tags=["Collaboration"])
app.include_router(copilot.router, prefix="/api/v1/reports", tags=["Interview Co-Pilot"])

@app.get("/", include_in_schema=False)
async def root():
    return {"product": "HireLens API", "version": "1.0.0", "docs": "/docs" if _docs_enabled else None}
