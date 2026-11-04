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


class ServiceUnavailable(FinboardError):
    code = "service_unavailable"
    title = "Service unavailable"


class PayloadTooLarge(FinboardError):
    code = "payload_too_large"
    title = "File too large"


class ReconciliationMismatch(Conflict):
    code = "reconciliation_mismatch"
    title = "The statement doesn't reconcile"
