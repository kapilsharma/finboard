"""Structured logging (ADR-0029).

Everything — our code, uvicorn, Celery — goes through one structlog pipeline. Request/job
context (request_id, user_id, job_id) is bound with contextvars. A redaction step drops values
that could carry statement contents or secrets, whatever log level is set.
"""

import logging
from collections.abc import MutableMapping
from typing import Any

import structlog

_REDACTED = "[redacted]"
_SENSITIVE_KEYS = frozenset({"password", "secret", "token", "file_name", "payee", "notes"})
_SENSITIVE_PREFIXES = ("password", "secret", "description", "amount", "balance")


def redact_sensitive(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event_dict):
        lowered = key.lower()
        if lowered in _SENSITIVE_KEYS or lowered.startswith(_SENSITIVE_PREFIXES):
            event_dict[key] = _REDACTED
    return event_dict


def configure_logging(level: str = "INFO", *, json: bool = True) -> None:
    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_sensitive,
    ]
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())

    for name in ("uvicorn", "uvicorn.error", "celery"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    # We log one line per request ourselves (api.middleware), with request_id and timing.
    logging.getLogger("uvicorn.access").disabled = True
