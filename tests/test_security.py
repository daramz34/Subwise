from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings
from app.core.security import (
    create_access_token, decode_access_token, generate_opaque_token, hash_password,
    hash_token, verify_password,
)


# ---- passwords ----
def test_hash_is_not_the_password_and_verifies():
    h = hash_password("Correct1Horse")
    assert h != "Correct1Horse"
    assert verify_password("Correct1Horse", h)


def test_wrong_password_fails():
    assert not verify_password("wrong-pass1", hash_password("Correct1Horse"))


def test_same_password_gives_different_hashes():
    assert hash_password("Correct1Horse") != hash_password("Correct1Horse")


def test_very_long_password_works_and_is_not_truncated():
    long_pw = "a1" * 60  # 120 characters, well past bcrypt's 72-byte limit
    h = hash_password(long_pw)
    assert verify_password(long_pw, h)
    assert not verify_password(long_pw[:72], h)  # a truncated version must NOT match


def test_garbage_hash_returns_false_not_error():
    assert verify_password("anything1", "not-a-bcrypt-hash") is False


# ---- access tokens ----
def test_access_token_round_trip():
    assert decode_access_token(create_access_token("user-123")) == "user-123"


def test_tampered_token_rejected():
    token = create_access_token("user-123")
    assert decode_access_token(token[:-3] + "abc") is None


def test_expired_token_rejected():
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    token = jwt.encode(
        {"sub": "u", "type": "access", "exp": past},
        settings.SECRET_KEY, algorithm=settings.ALGORITHM,
    )
    assert decode_access_token(token) is None


def test_wrong_token_type_rejected():
    future = datetime.now(timezone.utc) + timedelta(minutes=5)
    token = jwt.encode(
        {"sub": "u", "type": "refresh", "exp": future},
        settings.SECRET_KEY, algorithm=settings.ALGORITHM,
    )
    assert decode_access_token(token) is None


def test_token_signed_with_other_secret_rejected():
    future = datetime.now(timezone.utc) + timedelta(minutes=5)
    token = jwt.encode(
        {"sub": "u", "type": "access", "exp": future},
        "x" * 40, algorithm=settings.ALGORITHM,
    )
    assert decode_access_token(token) is None


def test_garbage_token_rejected():
    assert decode_access_token("not.a.jwt") is None


# ---- opaque tokens ----
def test_opaque_tokens_are_unique_and_hash_matches():
    raw1, h1 = generate_opaque_token()
    raw2, h2 = generate_opaque_token()
    assert raw1 != raw2
    assert h1 == hash_token(raw1)
    assert h1 != raw1 and len(h1) == 64