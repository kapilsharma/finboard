"""Domain errors. Raised anywhere below the API layer; `api.errors` maps them to HTTP problems.

Each error has a stable `code` that clients can rely on (the `detail` text may change).
"""


class FinboardError(Exception):
    code = "error"
    title = "Request failed"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.title
        super().__init__(self.detail)


class NotFound(FinboardError):
    code = "not_found"
    title = "Not found"


class Conflict(FinboardError):
    code = "conflict"
    title = "Conflict"


class ValidationFailed(FinboardError):
    code = "validation_failed"
    title = "Validation failed"


class Unauthenticated(FinboardError):
    code = "unauthenticated"
    title = "Not signed in"


class Forbidden(FinboardError):
    code = "forbidden"
    title = "Not allowed"


class CsrfFailed(Forbidden):
    """A signed-in request that changes something came without the session's CSRF token."""

    code = "csrf_check_failed"
    title = "This request could not be verified; reload the page and try again"


class SignupClosed(Forbidden):
    code = "signup_closed"
    title = "Sign-up is closed on this server"


class InvalidCredentials(Unauthenticated):
    code = "invalid_credentials"
    title = "Wrong username or password"


class RateLimited(FinboardError):
    code = "rate_limited"
    title = "Too many requests; wait a little and try again"

    def __init__(self, detail: str | None = None, *, retry_after: int = 60) -> None:
        super().__init__(detail)
        self.retry_after = retry_after


class ServiceUnavailable(FinboardError):
    code = "service_unavailable"
    title = "Service unavailable"


class PayloadTooLarge(FinboardError):
    code = "payload_too_large"
    title = "File too large"


class StorageQuotaExceeded(PayloadTooLarge):
    code = "storage_quota_exceeded"
    title = "Your storage is full"


class ReconciliationMismatch(Conflict):
    code = "reconciliation_mismatch"
    title = "The statement doesn't reconcile"


class AiFeatureOff(NotFound):
    """The AI feature isn't available on this server, or this user hasn't turned it on."""

    code = "ai_off"
    title = "This AI feature is off"


class QueryTimeout(ServiceUnavailable):
    """A read-only Ask query ran past its statement timeout."""

    code = "query_timeout"
    title = "That question took too long to answer"


class AiUnavailable(ServiceUnavailable):
    """The AI provider is rate-limiting, timing out or unreachable (ADR-0030)."""

    code = "ai_unavailable"
    title = "The AI service is busy; try again shortly"
