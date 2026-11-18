"""
Request body size limits, enforced before the body is parsed.

FastAPI parses a multipart upload completely — spooling every file to disk —
before the endpoint runs, so the size checks inside the upload handlers only
ever saw a body that had already been received in full. A single request of a
few gigabytes, from any signed-up account or none, would fill the container's
disk or memory first and be rejected second.

This middleware refuses a request whose declared Content-Length is over the
limit for its route before reading a byte, and counts the bytes of requests
that declare no length (chunked uploads) as they arrive, stopping at the
limit. The per-route caps sit a little above the application-level limits so
those keep producing their more specific messages.
"""

from starlette.responses import JSONResponse

from app.core.config import settings

_MB = 1024 * 1024
# Multipart framing, field headers and the JD text that rides with a batch.
_OVERHEAD = 2 * _MB


def limit_for(path: str) -> int:
    """The largest body, in bytes, accepted on `path`."""
    batch_paths = ("/api/v1/bulk/upload", "/api/v1/match/upload")
    if path in batch_paths:
        return int(settings.BULK_MAX_TOTAL_MB * 1.1 * _MB) + _OVERHEAD
    if path in ("/api/v1/analysis/upload", "/api/v1/ats/import"):
        return settings.MAX_FILE_SIZE_MB * _MB + _OVERHEAD
    # Every JSON endpoint. The largest legitimate body is a bulk notify with
    # per-candidate message overrides, comfortably under this.
    return 6 * _MB


class BodySizeLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return

        limit = limit_for(scope.get("path", ""))

        declared = None
        for name, value in scope.get("headers") or []:
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = None
                break

        def too_large(size_mb: float | None) -> JSONResponse:
            shown = f" ({size_mb:.0f} MB)" if size_mb else ""
            return JSONResponse(
                status_code=413,
                content={
                    "error": "payload_too_large",
                    "message": (
                        f"That upload is too large{shown}. "
                        f"The limit here is {limit / _MB:.0f} MB."
                    ),
                },
                headers={"Connection": "close"},
            )

        if declared is not None and declared > limit:
            await too_large(declared / _MB)(scope, receive, send)
            return

        received = 0
        exceeded = False
        replaced = False

        async def counted_receive():
            nonlocal received, exceeded
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body") or b"")
                if received > limit:
                    exceeded = True
                    # Stop reading. Whatever the app's body parser turns this
                    # into — Starlette's multipart parser rewraps every
                    # exception as "400 Invalid multipart data" — the response
                    # is replaced below, so the client gets an honest 413.
                    raise _BodyTooLarge()
            return message

        async def guarded_send(message):
            nonlocal replaced
            if not exceeded:
                await send(message)
                return
            if not replaced and message.get("type") == "http.response.start":
                replaced = True
                await too_large(None)(scope, receive, send)
            # Swallow the app's own response for the aborted request.

        try:
            await self.app(scope, counted_receive, guarded_send)
        except _BodyTooLarge:
            if not replaced:
                replaced = True
                await too_large(None)(scope, receive, send)


class _BodyTooLarge(Exception):
    """Raised inside receive() once a streamed body passes its limit."""
