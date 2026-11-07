"""Security helpers: password hashing, access tokens (JWT), refresh/reset tokens.

- Passwords: bcrypt, with a SHA-256 pre-hash so long passwords are never silently
  truncated (bcrypt only reads the first 72 bytes and newer versions raise an error).
- Access tokens: short-lived JWTs.
- Refresh and reset tokens: random opaque strings. Only their SHA-256 hash is stored
  in the database, so a database leak does not leak usable tokens.
"""
import base64
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

ACCESS_TOKEN_TYPE = "access"


# --------------------------------------------------------------------------
# Passwords
# --------------------------------------------------------------------------
def _prehash(password: str) -> bytes:
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)  # 44 bytes, always under bcrypt's 72-byte limit


def hash_password(password: str) -> str:
    return bcrypt.hashpw(
        _prehash(password), bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)
    ).decode("utf-8")
def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = hash_password("not-a-real-password")


def burn_password_check(password: str) -> None:
    """Call this when the email doesn't exist, so a missing account takes as long to
    reject as a wrong password. Otherwise response time reveals which emails are registered."""
    verify_password(password, _DUMMY_HASH)


# --------------------------------------------------------------------------
# Access tokens (JWT)
# --------------------------------------------------------------------------
def create_access_token(user_id: uuid.UUID | str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Returns the user id (as a string) if the token is valid, otherwise None."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],  # fixed list: never trust the token's own header
            options={"require": ["exp", "sub", "type"]},
        )
    except jwt.PyJWTError:
        return None
    if payload.get("type") != ACCESS_TOKEN_TYPE:
        return None
    return payload["sub"]


def access_token_ttl_seconds() -> int:
    return settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


# --------------------------------------------------------------------------
# Opaque tokens (refresh tokens, password-reset tokens)
# --------------------------------------------------------------------------
def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()  # 64 chars


def generate_opaque_token() -> tuple[str, str]:
    """Returns (raw_token, token_hash). Send the raw token to the user, store only the hash."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_token(raw)


def refresh_token_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)


def reset_token_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=settings.RESET_TOKEN_EXPIRE_MINUTES)