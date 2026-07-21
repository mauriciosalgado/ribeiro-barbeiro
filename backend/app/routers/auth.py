"""Registration, login, and password reset."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
import jwt
from pydantic import field_validator
from sqlmodel import SQLModel, select

from app.config import get_settings
from app.database import SessionDep
from app.email import send_email
from app.limiter import limiter
from app.models import User, UserCreate, UserRead, UserUpdate
from app.models.barber import Barber
from app.security import (
    CurrentUser,
    authenticate_user,
    create_access_token,
    create_reset_token,
    create_verification_token,
    hash_password,
    read_reset_token,
    read_verification_token,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


class ForgotPasswordRequest(SQLModel):
    email: str


class ResetPasswordRequest(SQLModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def check_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters")
        return value


class ChangePasswordRequest(SQLModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def check_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters")
        return value


def _send_verification_email(user: User) -> None:
    """Email the user a verification link; a mail outage must not block signup.

    Points at the *frontend's* /verify page (not this API directly) — the
    frontend calls GET /auth/verify itself, server-side, so the booking API
    never needs to be reachable from the browser just for this.
    """
    assert user.id is not None
    settings = get_settings()
    base = settings.frontend_url or settings.public_base_url
    link = f"{base}/verify?token={create_verification_token(user.id)}"
    try:
        send_email(user.email, "Verify your email", f"Confirm your account: {link}")
    except OSError as error:
        logger.warning("Could not send verification email to %s: %s", user.email, error)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def register(data: UserCreate, session: SessionDep, request: Request) -> User:
    if session.exec(select(User).where(User.email == data.email)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(
        email=data.email,
        full_name=data.full_name,
        hashed_password=hash_password(data.password),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    _send_verification_email(user)
    return user


@router.get("/verify")
def verify_email(token: str, session: SessionDep) -> dict[str, str]:
    try:
        user_id = read_verification_token(token)
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Invalid or expired token"
        ) from None
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    user.is_verified = True
    session.add(user)
    session.commit()
    return {"status": "verified"}


@router.post("/resend-verification")
def resend_verification(user: CurrentUser) -> dict[str, str]:
    if user.is_verified:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email already verified")
    _send_verification_email(user)
    return {"status": "sent"}


@router.post("/token", response_model=Token)
@limiter.limit("10/minute")
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: SessionDep,
    request: Request,
) -> Token:
    user = authenticate_user(session, form.username, form.password)
    if not user:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    assert user.id is not None
    barber = session.exec(select(Barber).where(Barber.user_id == user.id)).first()
    token = create_access_token(
        user.id, is_admin=user.is_admin, barber_id=barber.id if barber else 0
    )
    return Token(access_token=token)


@router.post("/forgot-password")
@limiter.limit("3/minute")
def forgot_password(
    data: ForgotPasswordRequest, session: SessionDep, request: Request
) -> dict[str, str]:
    """Send a password-reset link. Always returns 200 to avoid leaking emails."""
    user = session.exec(
        select(User).where(User.email == data.email.strip().lower())
    ).first()
    if user and user.id is not None:
        base = get_settings().frontend_url or get_settings().public_base_url
        link = f"{base}/reset-password?token={create_reset_token(user.id)}"
        try:
            send_email(
                user.email, "Reset your password", f"Reset your password: {link}"
            )
        except OSError as error:
            logger.warning("Could not send reset email to %s: %s", user.email, error)
    return {"status": "sent"}


@router.post("/reset-password")
@limiter.limit("5/minute")
def reset_password(
    data: ResetPasswordRequest, session: SessionDep, request: Request
) -> dict[str, str]:
    """Set a new password using a valid reset token."""
    try:
        user_id = read_reset_token(data.token)
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Invalid or expired token"
        ) from None
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    user.hashed_password = hash_password(data.new_password)
    session.add(user)
    session.commit()
    return {"status": "password_updated"}


@router.get("/me", response_model=UserRead)
def me(user: CurrentUser) -> User:
    return user


@router.put("/me/password")
def change_password(
    data: ChangePasswordRequest, session: SessionDep, user: CurrentUser
) -> dict[str, str]:
    """Let a signed-in user change their password (must know the current one)."""
    if not authenticate_user(session, user.email, data.current_password):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Current password is incorrect")
    user.hashed_password = hash_password(data.new_password)
    session.add(user)
    session.commit()
    return {"status": "password_updated"}


@router.patch("/me", response_model=UserRead)
def update_me(data: UserUpdate, session: SessionDep, user: CurrentUser) -> User:
    """Let a signed-in user edit their own name and phone number."""
    user.full_name = data.full_name
    user.phone = data.phone
    session.add(user)
    session.commit()
    session.refresh(user)
    return user
