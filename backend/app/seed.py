"""Seed the shop on startup: owner account, owner-as-barber, logo, services."""

from pathlib import Path

from sqlmodel import Session, select

from app.config import get_settings
from app.database import engine
from app.models import Barber, Service, Setting, User
from app.security import hash_password

# Bundled logo used when the shop hasn't uploaded one yet.
_DEFAULT_LOGO = Path(__file__).parent / "assets" / "default-logo.jpg"

# Services every new barber starts with; the barber renames or re-times them.
DEFAULT_SERVICES: tuple[tuple[str, int], ...] = (
    ("Corte", 30),
    ("Barba", 15),
)


def seed_default_services(session: Session, barber_id: int) -> None:
    """Give a barber the default services if they have none yet.

    Called on startup for every existing barber, and inline when a new barber is
    created (via the API or the admin console). Never touches a barber who already
    has services, so renamed or removed services are kept.
    """
    has_any = session.exec(
        select(Service).where(Service.barber_id == barber_id).limit(1)
    ).first()
    if has_any is not None:
        return
    for name, minutes in DEFAULT_SERVICES:
        session.add(Service(barber_id=barber_id, name=name, duration_minutes=minutes))


def seed_owner() -> None:
    """Create the owner from config, or keep an existing one in sync.

    Also makes the owner a barber (the common one-man-shop case). If the owner
    is already a barber, this is a no-op.
    """
    settings = get_settings()
    with Session(engine) as session:
        owner = session.exec(
            select(User).where(User.email == settings.owner_email)
        ).first()
        if owner is None:
            owner = User(
                email=settings.owner_email,
                hashed_password=hash_password(settings.owner_password),
                full_name=settings.owner_name,
            )
        # Guarantee the owner's role on every start, but never overwrite their
        # password or name — so an owner who edits either in-app keeps it.
        owner.is_admin = True
        owner.is_verified = True
        session.add(owner)
        session.commit()
        session.refresh(owner)

        # Make the owner a barber if they aren't one yet.
        assert owner.id is not None
        barber = session.exec(select(Barber).where(Barber.user_id == owner.id)).first()
        if barber is None:
            barber = Barber(user_id=owner.id)
            session.add(barber)
            session.commit()
            session.refresh(barber)
        assert barber.id is not None
        seed_default_services(session, barber.id)
        session.commit()


def seed_logo() -> None:
    """Give the shop a logo on first start; never clobber an uploaded one.

    Uses ``SHOP_LOGO_PATH`` if set, otherwise the bundled default. From then on
    the database is the source of truth and the owner replaces it from the UI.
    """
    with Session(engine) as session:
        if session.get(Setting, "logo") is not None:
            return
        source = get_settings().shop_logo_path
        path = Path(source) if source else _DEFAULT_LOGO
        if not path.is_file():
            return
        suffix = path.suffix.lower()
        content_type = "image/png" if suffix == ".png" else "image/jpeg"
        session.add(
            Setting(key="logo", content_type=content_type, data=path.read_bytes())
        )
        session.commit()


def seed_services() -> None:
    """Ensure every barber has at least the default services.

    Runs on every startup as a safety net — the primary seeding happens inline
    when a barber is created (API or admin console). This catches barbers that
    were somehow left without services (e.g. manual DB edits, migrations).
    """
    with Session(engine) as session:
        barbers = session.exec(select(Barber)).all()
        for barber in barbers:
            assert barber.id is not None
            seed_default_services(session, barber.id)
        session.commit()
