"""Pure pieces of server mode (M8, ADR-0041): passwords, cookies, configuration checks."""

import pytest

from finboard.auth import passwords
from finboard.auth.sessions import cookie_name, session_cookie
from finboard.core.config import Mode, Settings
from finboard.domain.errors import ValidationFailed
from finboard.main import create_app
from finboard.services.auth import normalise_username

PASSWORD = "a long enough passphrase"


def test_hashes_are_argon2id_salted_and_verify() -> None:
    first, second = passwords.hash_password(PASSWORD), passwords.hash_password(PASSWORD)
    assert first.startswith("$argon2id$") and first != second
    assert passwords.verify_password(first, PASSWORD)
    assert not passwords.verify_password(first, PASSWORD + "x")
    assert not passwords.needs_rehash(first)


def test_a_missing_or_broken_hash_never_verifies() -> None:
    assert not passwords.verify_password(None, PASSWORD)
    # Not even with the password the dummy hash was made from.
    assert not passwords.verify_password(None, "finboard-dummy-password")
    assert not passwords.verify_password("not-a-hash", PASSWORD)
    assert not passwords.verify_password("", PASSWORD)


@pytest.mark.parametrize("password", ["short", "x" * 129, "CarolCarol1"])
def test_password_policy_refuses(password: str) -> None:
    with pytest.raises(ValidationFailed):
        passwords.check_policy(password, username="carolcarol1")


def test_password_policy_is_about_length_not_symbols() -> None:
    passwords.check_policy("only lowercase words", username="carol")


@pytest.mark.parametrize(
    ("raw", "expected"), [("Carol", "carol"), ("  a.b-c_1 ", "a.b-c_1"), ("x" * 32, "x" * 32)]
)
def test_usernames_are_normalised(raw: str, expected: str) -> None:
    assert normalise_username(raw) == expected


@pytest.mark.parametrize("raw", ["ab", "x" * 33, ".dot", "has space", "a/b", "ünï", ""])
def test_bad_usernames_are_refused(raw: str) -> None:
    with pytest.raises(ValidationFailed):
        normalise_username(raw)


def test_session_cookie_is_read_from_the_header() -> None:
    headers = {"cookie": "theme=dark; finboard_session=abc123; other=1"}
    assert session_cookie(headers, "finboard_session") == "abc123"
    assert session_cookie(headers, "__Host-finboard_session") is None
    assert session_cookie({}, "finboard_session") is None
    assert cookie_name(secure=True).startswith("__Host-")
    assert cookie_name(secure=False) == "finboard_session"


@pytest.mark.parametrize(
    ("public_url", "ok"),
    [
        (None, False),
        ("finboard.example.com", False),
        ("http://finboard.example.com", False),  # passwords in clear text
        ("https://finboard.example.com", True),
        ("http://127.0.0.1:8765", True),  # trying it out on your own machine
        ("http://localhost:8765", True),
    ],
)
def test_server_mode_needs_a_public_url_and_tls(public_url: str | None, ok: bool) -> None:
    settings = Settings(mode=Mode.SERVER, public_url=public_url)
    assert (settings.server_mode_problem() is None) is ok
    if ok:
        create_app(settings)
    else:
        with pytest.raises(RuntimeError, match="FINBOARD_PUBLIC_URL"):
            create_app(settings)


def test_the_public_host_joins_the_allow_list_in_server_mode_only() -> None:
    server = Settings(mode=Mode.SERVER, public_url="https://finboard.example.com")
    assert "finboard.example.com" in server.effective_allowed_hosts
    assert server.cookie_secure
    local = Settings(public_url="https://finboard.example.com")
    assert "finboard.example.com" not in local.effective_allowed_hosts
    assert not Settings(mode=Mode.SERVER, public_url="http://127.0.0.1:8765").cookie_secure
