"""Reusable FastAPI dependencies.

get_current_user  -> the logged-in user, or 401
get_user_plan     -> the plan the user currently has access to (free if none/expired/revoked)
require_plan(...) -> 403 unless the user's plan is one of the given codes
"""
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.database import get_db
from app.models import Plan, User, UserEntitlement

# Must match the real login route, because Swagger's "Authorize" button posts here
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


def _unauthorized() -> HTTPException:
    # One generic message for every failure, so callers can't tell WHY a token was rejected
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    sub = decode_access_token(token)
    if sub is None:
        raise _unauthorized()

    try:
        user_id = uuid.UUID(sub)  # ids are UUIDs here, not integers
    except ValueError:
        raise _unauthorized()

    user = db.get(User, user_id)
    if user is None:
        raise _unauthorized()
    return user


def get_user_plan(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Plan:
    """The plan that applies RIGHT NOW. A revoked, expired or missing entitlement means Free."""
    entitlement = db.scalar(
        select(UserEntitlement).where(UserEntitlement.user_id == user.id)
    )
    now = datetime.now(timezone.utc)
    if (
        entitlement is not None
        and entitlement.status == "active"
        and (entitlement.expires_at is None or entitlement.expires_at > now)
    ):
        return entitlement.plan

    free = db.scalar(select(Plan).where(Plan.code == "free"))
    if free is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Plans have not been seeded. Run: python -m app.seed",
        )
    return free


def require_plan(*allowed_codes: str) -> Callable[..., Plan]:
    """Usage: Depends(require_plan("plus")) on any route that needs a paid plan."""
    allowed = set(allowed_codes)

    def dependency(plan: Plan = Depends(get_user_plan)) -> Plan:
        if plan.code not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This feature needs a paid plan. Upgrade to continue.",
            )
        return plan

    return dependency


# Shorthand so route signatures stay readable:
#   def my_route(user: CurrentUser, db: DbSession): ...
CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_db)]
UserPlan = Annotated[Plan, Depends(get_user_plan)]