"""Password hashing: argon2id through argon2-cffi, with the library's current defaults
(RFC 9106's low-memory profile). Hashes carry their own parameters, so raising the cost later
only needs `needs_rehash` at the next sign-in. Hashing is CPU work: call it off the event loop.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from finboard.domain.errors import ValidationFailed

MIN_LENGTH = 10
MAX_LENGTH = 128  # argon2 takes any length; the cap stops a huge body from costing CPU

_hasher = PasswordHasher()
# Verified against when the username doesn't exist, so a wrong username takes as long as a
# wrong password and the response time doesn't reveal which accounts exist.
_DUMMY_HASH = _hasher.hash("finboard-dummy-password")


def check_policy(password: str, *, username: str) -> None:
    """Length is what matters for a password; composition rules aren't imposed."""
    if len(password) < MIN_LENGTH:
        raise ValidationFailed(f"Use a password of at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        raise ValidationFailed(f"Use a password of at most {MAX_LENGTH} characters")
    if password.lower() == username.lower():
        raise ValidationFailed("The password can't be the same as the username")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """True when `password` matches. A missing hash (no such user, or a user who has no
    password yet) still does the work of a verification."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)
