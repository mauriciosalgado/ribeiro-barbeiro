"""User accounts."""

from pydantic import EmailStr, field_validator
from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(unique=True)
    hashed_password: str
    full_name: str
    phone: str | None = None
    is_admin: bool = False
    is_verified: bool = False

    def __str__(self) -> str:
        return self.full_name


class UserCreate(SQLModel):
    email: EmailStr
    full_name: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("full_name")
    @classmethod
    def require_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("Name cannot be empty")
        return name

    @field_validator("password")
    @classmethod
    def check_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters")
        return value


class UserUpdate(SQLModel):
    """The fields a signed-in user may change about their own account."""

    full_name: str
    phone: str | None = None

    @field_validator("full_name")
    @classmethod
    def require_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("Name cannot be empty")
        return name

    @field_validator("phone")
    @classmethod
    def tidy_phone(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


class UserRead(SQLModel):
    id: int
    email: str
    full_name: str
    phone: str | None
    is_admin: bool
    is_verified: bool
