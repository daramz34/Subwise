"""Authentication business logic. Routers stay thin and call these functions."""
import logging
import math
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    access_token_ttl_seconds, burn_password_check, create_access_token,
    generate_opaque_token, hash_password, hash_token, refresh_token_expiry,
    reset_token_expiry, verify_password,
)
from app.models import (
    NotificationPreference, PasswordResetToken, Plan, RefreshToken, User, UserEntitlement,
)
from app.schemas import RegisterIn, TokenOut, UserUpdate

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _revoke_all_refresh_tokens(db: Session, user_id) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


# --------------------------------------------------------------------------
# Register
# --------------------------------------------------------------------------
def register_user(db: Session, data: RegisterIn) -> User:
    free_plan = db.scalar(select(Plan).where(Plan.code == "free"))
    if free_plan is None:
        raise HTTPException(500, "Plans have not been seeded. Run: python -m app.seed")

    if db.scalar(select(User.id).where(User.email == data.email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    user = User(
        full_name=data.full_name,
        email=data.email,  # already lowercased by the schema
        password_hash=hash_password(data.password),
        default_currency=data.default_currency,
        timezone=data.timezone,
    )
    db.add(user)
    try:
        db.flush()  # assigns user.id; also catches two simultaneous signups with the same email
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    db.add(UserEntitlement(user_id=user.id, plan_id=free_plan.id, status="active", activated_at=_now()))
    db.add(NotificationPreference(user_id=user.id))
    db.commit()
    db.refresh(user)
    return user


# --------------------------------------------------------------------------
# Login and lockout
# --------------------------------------------------------------------------
def authenticate(db: Session, email: str, password: str) -> User:
    invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")

    user = db.scalar(select(User).where(User.email == email.lower()))
    if user is None:
        burn_password_check(password)  # same response time as a wrong password
        raise invalid

    now = _now()
    # Checked BEFORE the password, so a correct password can't be used to bypass a lockout
    if user.locked_until is not None and user.locked_until > now:
        seconds = int((user.locked_until - now).total_seconds()) + 1
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many failed attempts. Try again in {math.ceil(seconds / 60)} minute(s).",
            headers={"Retry-After": str(seconds)},
        )

    if not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.MAX_FAILED_LOGINS:
            user.locked_until = now + timedelta(minutes=settings.LOCKOUT_MINUTES)
            user.failed_login_count = 0
        db.commit()  # commit BEFORE raising, otherwise the counter change is rolled back
        raise invalid

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    db.commit()
    return user


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------
def issue_tokens(db: Session, user: User, user_agent: str | None) -> TokenOut:
    raw, token_hash = generate_opaque_token()
    db.add(RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        user_agent=user_agent[:255] if user_agent else None,
        expires_at=refresh_token_expiry(),
    ))
    db.commit()
    return TokenOut(
        access_token=create_access_token(user.id),
        refresh_token=raw,
        expires_in=access_token_ttl_seconds(),
    )


def refresh_tokens(db: Session, raw_token: str, user_agent: str | None) -> TokenOut:
    invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token")

    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token)))
    if row is None:
        raise invalid

    if row.revoked_at is not None:
        # An already-rotated token is being used again: it may have been stolen.
        # Kill every session for this user so the thief's copy dies too.
        _revoke_all_refresh_tokens(db, row.user_id)
        db.commit()
        raise invalid

    if row.expires_at <= _now():
        raise invalid

    # Atomic claim: if two requests rotate the same token at once, only one wins
    claimed = db.execute(
        update(RefreshToken)
        .where(RefreshToken.id == row.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise invalid

    user = db.get(User, row.user_id)
    if user is None:
        db.rollback()
        raise invalid
    return issue_tokens(db, user, user_agent)  # commits the revoke and the new token together


def logout(db: Session, raw_token: str) -> None:
    """Idempotent: an unknown or already-revoked token is not an error."""
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token)))
    if row is not None and row.revoked_at is None:
        row.revoked_at = _now()
        db.commit()


# --------------------------------------------------------------------------
# Password reset and change
# --------------------------------------------------------------------------
def create_reset_token(db: Session, email: str) -> str | None:
    """Returns the raw token (to be emailed), or None if the email isn't registered.
    The route returns the same message either way, so callers can't probe for accounts."""
    user = db.scalar(select(User).where(User.email == email.lower()))
    if user is None:
        return None

    # Only the newest reset link works
    db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=_now())
    )
    raw, token_hash = generate_opaque_token()
    db.add(PasswordResetToken(user_id=user.id, token_hash=token_hash, expires_at=reset_token_expiry()))
    db.commit()

    # TODO: send this by email once an email provider is chosen.
    if settings.ENVIRONMENT == "development":
        logger.warning("DEV ONLY: password reset token for %s: %s", user.email, raw)
    return raw


def reset_password(db: Session, raw_token: str, new_password: str) -> None:
    invalid = HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired reset token")

    row = db.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(raw_token))
    )
    now = _now()
    if row is None or row.used_at is not None or row.expires_at <= now:
        raise invalid

    # Atomic single-use claim
    claimed = db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.id == row.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise invalid

    user = db.get(User, row.user_id)
    user.password_hash = hash_password(new_password)
    user.failed_login_count = 0
    user.locked_until = None
    _revoke_all_refresh_tokens(db, user.id)  # a reset logs out every device
    db.commit()


def change_password(db: Session, user: User, current_password: str, new_password: str) -> None:
    if not verify_password(current_password, user.password_hash):
        # 400, not 401: a 401 would make the frontend think the session expired
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    if verify_password(new_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New password must be different")

    user.password_hash = hash_password(new_password)
    _revoke_all_refresh_tokens(db, user.id)
    db.commit()


# --------------------------------------------------------------------------
# Profile and account
# --------------------------------------------------------------------------
def update_profile(db: Session, user: User, data: UserUpdate) -> User:
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


def delete_account(db: Session, user: User) -> None:
    if user.is_demo:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The demo account cannot be deleted")
    db.delete(user)  # every user-owned table cascades from users
    db.commit()