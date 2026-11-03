"""Pure ASGI middleware (no BaseHTTPMiddleware: it buffers and breaks streaming)."""

import re
import time
import uuid
from collections.abc import Iterable
from urllib.parse import urlsplit

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from finboard.api.errors import problem

log = structlog.get_logger("finboard.request")

_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CLIENT_HEADER = "x-finboard-client"


class RequestContextMiddleware:
    """Request id (echoed as X-Request-ID), log context, and one log line per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get("x-request-id", "")
        request_id = incoming if _REQUEST_ID.match(incoming) else uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        status = 500
        started = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message).append("X-Request-ID", request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            log.info(
                "request",
                method=scope["method"],
                path=scope["path"],
                status=status,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            structlog.contextvars.clear_contextvars()


def _hostname(host_header: str) -> str:
    if host_header.startswith("["):  # [::1]:8765
        return host_header[1 : host_header.find("]")].lower()
    return (
        host_header.rsplit(":", 1)[0].lower()
        if host_header.count(":") == 1
        else host_header.lower()
    )


class SecurityMiddleware:
    """Local-mode request guards (ADR-0015).

    * Host allow-list → stops DNS rebinding (a hostile domain resolving to 127.0.0.1).
    * Mutating requests need `X-Finboard-Client: 1` → a cross-site page can't send that header
      without a CORS preflight, which we never approve. This blocks CSRF via forms/uploads.
    * If the browser sends `Origin`, it must be our own origin.
    """

    def __init__(self, app: ASGIApp, allowed_hosts: Iterable[str]) -> None:
        self.app = app
        self.allowed_hosts = frozenset(h.lower().strip("[]") for h in allowed_hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        host = headers.get("host", "")
        if _hostname(host) not in self.allowed_hosts:
            response = problem(421, "host_not_allowed", "Host not allowed")
            await response(scope, receive, send)
            return

        if scope["method"] not in _SAFE_METHODS:
            if headers.get(CLIENT_HEADER) != "1":
                response = problem(403, "csrf_check_failed", "Missing X-Finboard-Client header")
                await response(scope, receive, send)
                return
            origin = headers.get("origin")
            if origin is not None and urlsplit(origin).netloc.lower() != host.lower():
                response = problem(403, "csrf_check_failed", "Cross-origin request refused")
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)
