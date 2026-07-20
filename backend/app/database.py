"""Database engine and per-request session."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings

url = get_settings().database_url
# SQLite (local dev) needs this flag to work across FastAPI's threads.
connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
engine = create_engine(url, connect_args=connect_args)

if url.startswith("sqlite"):
    # SQLite ignores foreign keys unless asked; turn them on so ON DELETE CASCADE
    # behaves the same in dev as it does in Postgres.
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def init_db() -> None:
    """Create any tables that don't exist yet."""
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
