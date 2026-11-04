from finboard.core.logging import redact_sensitive


def test_sensitive_values_are_redacted() -> None:
    event = {
        "event": "import.parsed",
        "password": "hunter2",
        "description_raw": "UPI/SWIGGY",
        "amount": "123.45",
        "balance_after": "9000",
        "file_name": "statement_sep.pdf",
        "rows": 42,
        "user_id": "abc",
    }
    out = redact_sensitive(None, "info", dict(event))
    assert out["rows"] == 42
    assert out["user_id"] == "abc"
    for key in ("password", "description_raw", "amount", "balance_after", "file_name"):
        assert out[key] == "[redacted]"


def test_console_tracebacks_do_not_show_local_variables() -> None:
    """Dev logs (log_json=false) once printed every frame's locals via rich tracebacks."""
    import io
    import logging

    import structlog

    from finboard.core.logging import configure_logging

    configure_logging("INFO", json=False)
    stream = io.StringIO()
    handler = logging.getLogger().handlers[0]
    handler.setStream(stream)  # type: ignore[attr-defined]

    def parse_statement() -> None:
        statement_password = "Canary-Local-Var-91"  # noqa: F841
        raise ValueError("boom")

    try:
        parse_statement()
    except ValueError:
        structlog.get_logger("t").exception("job.failed")
    output = stream.getvalue()
    assert "ValueError" in output
    assert "Canary-Local-Var-91" not in output
