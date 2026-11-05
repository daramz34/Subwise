from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.deps import CurrentUser, DbSession
from app.core.limiter import RateLimiter
from app.schemas import (
    ChangePasswordIn, DetailOut, ForgotPasswordIn, LoginIn, RefreshIn, RegisterIn,
    ResetPasswordIn, TokenOut, UserOut, UserUpdate,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

# /login and /token share one limit bucket (scope "login")
login_limit = Depends(RateLimiter(times=10, seconds=60, scope="login"))


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(RateLimiter(times=5, seconds=60, scope="register"))])
def register(body: RegisterIn, db: DbSession):
    return auth_service.register_user(db, body)


@router.post("/login", response_model=TokenOut, dependencies=[login_limit])
def login(body: LoginIn, request: Request, db: DbSession):
    """JSON login, used by the frontend."""
    user = auth_service.authenticate(db, body.email, body.password)
    return auth_service.issue_tokens(db, user, request.headers.get("user-agent"))


@router.post("/token", response_model=TokenOut, dependencies=[login_limit], include_in_schema=True)
def token(form: Annotated[OAuth2PasswordRequestForm, Depends()], request: Request, db: DbSession):
    """Form login. Exists only so the Authorize button in /docs works (username = email)."""
    user = auth_service.authenticate(db, form.username, form.password)
    return auth_service.issue_tokens(db, user, request.headers.get("user-agent"))


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, request: Request, db: DbSession):
    return auth_service.refresh_tokens(db, body.refresh_token, request.headers.get("user-agent"))


@router.post("/logout", response_model=DetailOut)
def logout(body: RefreshIn, db: DbSession):
    auth_service.logout(db, body.refresh_token)
    return DetailOut(detail="Logged out")


@router.post("/forgot-password", response_model=DetailOut,
             dependencies=[Depends(RateLimiter(times=5, seconds=60, scope="forgot"))])
def forgot_password(body: ForgotPasswordIn, db: DbSession):
    auth_service.create_reset_token(db, body.email)
    # Identical answer whether or not the email exists
    return DetailOut(detail="If that email is registered, a reset link has been sent.")


@router.post("/reset-password", response_model=DetailOut,
             dependencies=[Depends(RateLimiter(times=10, seconds=60, scope="reset"))])
def reset_password(body: ResetPasswordIn, db: DbSession):
    auth_service.reset_password(db, body.token, body.new_password)
    return DetailOut(detail="Password updated. Please log in.")


@router.post("/change-password", response_model=DetailOut)
def change_password(body: ChangePasswordIn, user: CurrentUser, db: DbSession):
    auth_service.change_password(db, user, body.current_password, body.new_password)
    return DetailOut(detail="Password changed. Please log in again.")


@router.get("/me", response_model=UserOut)
def read_me(user: CurrentUser):
    return user


@router.patch("/me", response_model=UserOut)
def update_me(body: UserUpdate, user: CurrentUser, db: DbSession):
    return auth_service.update_profile(db, user, body)


@router.delete("/me", response_model=DetailOut)
def delete_me(user: CurrentUser, db: DbSession):
    auth_service.delete_account(db, user)
    return DetailOut(detail="Account deleted")