"""FastAPI app for booking haircuts at a single barber shop."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.admin import setup_admin
from app.config import get_settings
from app.database import init_db
from app.limiter import limiter
from app.routers import appointments, auth, barbers, closures, services, system
from app.routers import settings as settings_router
from app.seed import seed_logo, seed_owner, seed_services


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create tables and seed the shop owner on startup."""
    init_db()
    seed_owner()
    seed_logo()
    seed_services()
    yield


settings = get_settings()
app = FastAPI(title=f"{settings.shop_name} — Booking API", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(system.router)
app.include_router(auth.router)
app.include_router(barbers.router)
app.include_router(services.router)
app.include_router(appointments.router)
app.include_router(closures.router)
app.include_router(settings_router.router)
setup_admin(app)


def run() -> None:
    """Entry point for `uv run serve` — starts the dev server with auto-reload."""
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
