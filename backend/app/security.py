"""Password hashing and JWT authentication."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session, select

from app.config import get_settings
from app.database import SessionDep
from app.models import User

ALGORITHM = "HS256"
TOKEN_TTL = timedelta(days=1)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:  # stored value isn't a valid bcrypt hash
        return False


def authenticate_user(session: Session, email: str, password: str) -> User | None:
    """Return the user if the email/password match, otherwise None."""
    user = session.exec(select(User).where(User.email == email.strip().lower())).first()
    if user and verify_password(password, user.hashed_password):
        return user
    return None


def _create_token(user_id: int, purpose: str) -> str:
    payload = {
        "sub": str(user_id),
        "purpose": purpose,
        "exp": datetime.now(UTC) + TOKEN_TTL,
    }
    return jwt.encode(payload, get_settings().jwt_secret, algorithm=ALGORITHM)


def _read_token(token: str, purpose: str) -> int:
    """Decode a token and return its user id, or raise if it's the wrong kind."""
    payload = jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGORITHM])
    if payload.get("purpose") != purpose:
        raise jwt.InvalidTokenError("unexpected token purpose")
    return int(payload["sub"])


def create_access_token(user_id: int) -> str:
    return _create_token(user_id, "access")


def create_verification_token(user_id: int) -> str:
    return _create_token(user_id, "verify")


def create_reset_token(user_id: int) -> str:
    return _create_token(user_id, "reset")


def read_verification_token(token: str) -> int:
    return _read_token(token, "verify")


def read_reset_token(token: str) -> int:
    return _read_token(token, "reset")


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], session: SessionDep
) -> User:
    invalid = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        user_id = _read_token(token, "access")
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise invalid from None
    user = session.get(User, user_id)
    if user is None:
        raise invalid
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user


AdminUser = Annotated[User, Depends(require_admin)]
