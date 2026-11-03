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
