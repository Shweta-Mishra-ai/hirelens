"""HireLens API — Production FastAPI Application"""

from contextlib import asynccontextmanager
import time, uuid, logging

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.exceptions import (
    HireLensException, RateLimitExceeded,
    FileTooLarge, UnsupportedFileType, AuthError,
)
from app.api.v1.endpoints import analysis, reports, auth, health, bulk, match, verify, ats, teams, collaboration

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hirelens")


DEFAULT_SECRET_KEY = "dev-secret-key-change-in-production-min-32"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"HireLens API starting — env={settings.APP_ENV}")

    # ── Security startup checks ─────────────────────────────────────────────
    if settings.is_production:
        if settings.SECRET_KEY == DEFAULT_SECRET_KEY or len(settings.SECRET_KEY) < 32:
            logger.critical(
                "SECURITY: SECRET_KEY is unset or using the default dev value in "
                "production. JWTs can be forged by anyone who has read this public "
                "repo. Set a real random SECRET_KEY (32+ chars) in your environment "
                "immediately — e.g. `python -c \"import secrets; print(secrets.token_urlsafe(48))\"`."
            )
        if "*" in settings.allowed_origins_list:
            logger.critical(
                "SECURITY: ALLOWED_ORIGINS includes '*' in production — this allows "
                "any website to make authenticated requests to this API. Restrict it "
                "to your actual frontend domain(s)."
            )

    yield
    logger.info("HireLens API shutting down")


app = FastAPI(
    title="HireLens API",
    description="AI-powered recruiter decision intelligence. Gemini 2.5 Flash backend.",
    version="1.0.0",
    lifespan=lifespan,
)

# ── Middleware ────────────────────────────────────────────────────────────────
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Response-Time"],
)

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

# ── Exception Handlers ────────────────────────────────────────────────────────
@app.exception_handler(HireLensException)
async def hirelens_handler(request: Request, exc: HireLensException):
    rid = getattr(request.state, "request_id", "?")
    return JSONResponse(status_code=exc.http_status, content={
        "error": exc.code, "message": exc.message, "request_id": rid,
    })

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={
        "error": "rate_limit_exceeded",
        "message": f"Too many requests. Retry after {exc.retry_after}s.",
        "retry_after": exc.retry_after,
    }, headers={"Retry-After": str(exc.retry_after)})

@app.exception_handler(FileTooLarge)
async def file_too_large_handler(request: Request, exc: FileTooLarge):
    return JSONResponse(status_code=413, content={
        "error": "file_too_large",
        "message": f"File exceeds {exc.max_mb}MB limit.",
        "max_mb": exc.max_mb,
    })

@app.exception_handler(UnsupportedFileType)
async def unsupported_type_handler(request: Request, exc: UnsupportedFileType):
    return JSONResponse(status_code=415, content={
        "error": "unsupported_file_type",
        "message": f"'{exc.file_type}' not supported. Upload PDF or DOCX.",
    })

@app.exception_handler(AuthError)
async def auth_handler(request: Request, exc: AuthError):
    return JSONResponse(status_code=401, content={
        "error": "unauthorized", "message": exc.message,
    }, headers={"WWW-Authenticate": "Bearer"})

# ── Routes ────────────────────────────────────────────────────────────────────
app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(analysis.router, prefix="/api/v1/analysis", tags=["Analysis"])
app.include_router(bulk.router, prefix="/api/v1/bulk", tags=["Bulk Upload"])
app.include_router(match.router, prefix="/api/v1/match", tags=["JD Match"])
app.include_router(verify.router, prefix="/api/v1/verify", tags=["Verification"])
app.include_router(ats.router, prefix="/api/v1/ats", tags=["ATS Import"])
app.include_router(teams.router, prefix="/api/v1/teams", tags=["Teams"])
app.include_router(reports.router, prefix="/api/v1/reports", tags=["Reports"])
app.include_router(collaboration.router, prefix="/api/v1/reports", tags=["Collaboration"])

@app.get("/", include_in_schema=False)
async def root():
    return {"product": "HireLens API", "version": "1.0.0", "docs": "/docs"}
