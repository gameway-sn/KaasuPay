"""Password hashing (argon2) and the login token (JWT in a cookie)."""
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Response

from app.config import settings

COOKIE_NAME = "access_token"

_hasher = PasswordHasher()

# Used when the phone number doesn't exist, so a failed login takes the same
# time whether or not the account exists (an attacker can't time the reply
# to find out which phone numbers are registered).
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


# ---------- passwords ----------

def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        _hasher.verify(password_hash or _DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        return False
    return password_hash is not None


# ---------- login token ----------

def create_access_token(user_id: int) -> str:
    """A signed token saying "this is user N", valid for 30 minutes."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def read_access_token(token: str) -> int | None:
    """Return the user id, or None if the token is fake, edited or expired."""
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        return int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None


def set_login_cookie(response: Response, user_id: int) -> None:
    response.set_cookie(
        COOKIE_NAME,
        create_access_token(user_id),
        max_age=settings.access_token_minutes * 60,
        httponly=True,                  # JavaScript cannot read it
        samesite="lax",                 # not sent on form posts from other websites
        secure=settings.cookie_secure,  # HTTPS-only once we add HTTPS
        path="/",
    )


def clear_login_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")
