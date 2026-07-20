"""Shop appearance settings the owner can change from the UI.

The brand palette is two colours the owner picks: a *brand* colour (buttons,
links, highlights) and a *background* colour (the page — light or dark).
Everything else is derived in the frontend for legibility. The shop *logo* lives
here too, as a small image stored in the database. Anyone may read these (the
site needs them to paint itself); only an admin may change them.
"""

import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import field_validator
from sqlmodel import Session, SQLModel

from app.config import get_settings
from app.database import SessionDep
from app.models import Setting
from app.security import AdminUser

router = APIRouter(prefix="/settings", tags=["settings"])

# Bundled fallback served if the shop somehow has no logo row yet.
_DEFAULT_LOGO = Path(__file__).parent.parent / "assets" / "default-logo.jpg"

# Logos are small; refuse anything that clearly isn't a sensible icon upload.
_MAX_LOGO_BYTES = 2 * 1024 * 1024
_ALLOWED_LOGO_TYPES = {"image/png", "image/jpeg", "image/webp"}

# Colours are plain #rrggbb hex, so the owner has full control over the palette.
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

# A sensible cap so the sign-in headline stays a headline, not a paragraph.
_MAX_HEADLINE = 80

_BRAND_KEY = "theme_brand"
_BACKGROUND_KEY = "theme_background"
_HEADLINE_KEY = "shop_headline"


def _hex_field(value: str) -> str:
    if not _HEX.match(value):
        raise ValueError("colour must be a #rrggbb hex value")
    return value.lower()


class ThemeRead(SQLModel):
    brand: str
    background: str
    # The sign-in page headline, owner-editable and shown to signed-out visitors.
    headline: str
    # A cache-busting stamp for the logo, so the browser refetches it after the
    # owner uploads a new one. Changes whenever the logo changes.
    logo_version: str


class ThemeUpdate(SQLModel):
    brand: str
    background: str
    headline: str

    @field_validator("brand", "background")
    @classmethod
    def _check_hex(cls, v: str) -> str:
        return _hex_field(v)

    @field_validator("headline")
    @classmethod
    def _check_headline(cls, v: str) -> str:
        v = v.strip()
        if len(v) > _MAX_HEADLINE:
            raise ValueError(f"headline must be at most {_MAX_HEADLINE} characters")
        return v


def _get(session: Session, key: str, default: str) -> str:
    setting = session.get(Setting, key)
    return setting.value if setting else default


def _set(session: Session, key: str, value: str) -> None:
    setting = session.get(Setting, key)
    if setting:
        setting.value = value
    else:
        setting = Setting(key=key, value=value)
    session.add(setting)


def _logo_version(session: Session) -> str:
    logo = session.get(Setting, "logo")
    return str(logo.updated_at.timestamp()) if logo else "0"


def _read_theme(session: Session) -> ThemeRead:
    settings = get_settings()
    return ThemeRead(
        brand=_get(session, _BRAND_KEY, settings.shop_brand),
        background=_get(session, _BACKGROUND_KEY, settings.shop_background),
        headline=_get(session, _HEADLINE_KEY, settings.shop_headline),
        logo_version=_logo_version(session),
    )


@router.get("/theme", response_model=ThemeRead)
def read_theme(session: SessionDep) -> ThemeRead:
    return _read_theme(session)


@router.put("/theme", response_model=ThemeRead, status_code=status.HTTP_200_OK)
def update_theme(data: ThemeUpdate, session: SessionDep, admin: AdminUser) -> ThemeRead:
    _set(session, _BRAND_KEY, data.brand)
    _set(session, _BACKGROUND_KEY, data.background)
    _set(session, _HEADLINE_KEY, data.headline)
    session.commit()
    return _read_theme(session)


@router.get("/logo")
def read_logo(session: SessionDep) -> Response:
    """The shop's logo image. Falls back to the bundled default if unset."""
    logo = session.get(Setting, "logo")
    if logo and logo.data:
        return Response(
            content=logo.data,
            media_type=logo.content_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )
    return Response(content=_DEFAULT_LOGO.read_bytes(), media_type="image/jpeg")


@router.put("/logo", response_model=ThemeRead, status_code=status.HTTP_200_OK)
async def update_logo(
    file: UploadFile, session: SessionDep, admin: AdminUser
) -> ThemeRead:
    """Replace the shop's logo — applies live to every visitor, no restart."""
    if file.content_type not in _ALLOWED_LOGO_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="A imagem deve ser PNG, JPEG ou WEBP.",
        )
    data = await file.read()
    if len(data) > _MAX_LOGO_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="A imagem é demasiado grande (máx. 2 MB).",
        )

    logo = session.get(Setting, "logo")
    if logo:
        logo.content_type = file.content_type
        logo.data = data
        logo.updated_at = datetime.now(timezone.utc)
    else:
        logo = Setting(key="logo", content_type=file.content_type, data=data)
    session.add(logo)
    session.commit()
    return _read_theme(session)
