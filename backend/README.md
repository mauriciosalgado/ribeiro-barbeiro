# Backend

FastAPI + SQLModel REST API with a built-in admin console at `/admin` (SQLAdmin).

## Layout

```
app/
├── main.py           entry point, router wiring
├── config.py         settings (from environment)
├── database.py       engine + session dependency
├── security.py       bcrypt, JWT, auth guards
├── email.py          SMTP helper
├── limiter.py        rate limiting
├── seed.py           first-start seeding (owner, barber, services, logo)
├── scheduling.py     slot generation (pure logic, no I/O)
├── availability.py   open slots (hours − lunch − booked − closures − past)
├── admin.py          /admin console (SQLAdmin views + validation)
├── models/           one file per entity (table + schemas)
└── routers/          one file per resource (auth, barbers, appointments, closures, services, settings, system)
tests/                pytest suite
```

## Run locally

```bash
uv sync
cp .env.example .env
uv run serve
```

- API docs → http://127.0.0.1:8000/docs
- Admin console → http://127.0.0.1:8000/admin

## Tests

```bash
uv run pytest
```

109 tests covering: slot logic, booking rules, email verification, password
reset, closures, services, recurrence, and permissions.

## Configuration

All values in `.env.example` are required — a missing one stops the app at startup.

| Variable | Purpose |
| -------- | ------- |
| `SHOP_NAME` | Header, emails, API title |
| `SHOP_TIMEZONE` | IANA timezone for scheduling |
| `OWNER_EMAIL`, `OWNER_NAME`, `OWNER_PASSWORD` | Admin account, seeded on first start |
| `JWT_SECRET` | Signs all tokens — `openssl rand -hex 32`. The frontend needs this same value too, to verify tokens locally (see frontend/README.md) |
| `DATABASE_URL` | `sqlite:///./barber.db` (dev) or `postgresql://…` (prod) |
| `CORS_ORIGINS` | Allowed browser origins, comma-separated or `*` |
| `PUBLIC_BASE_URL` | Fallback base URL for email links if `FRONTEND_URL` is unset |
| `FRONTEND_URL` | Frontend URL used in password-reset/verification email links (e.g. `.../verify?token=...`) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM` | Outgoing mail; empty host = disabled |
| `SMTP_STARTTLS`, `SMTP_USERNAME`, `SMTP_PASSWORD` | TLS + auth for production |
| `SHOP_BRAND`, `SHOP_BACKGROUND`, `SHOP_HEADLINE` | Initial theme (owner overrides from UI) |
| `SHOP_LOGO_PATH` | Optional: seed logo from a file on first start |

## Design

- **Availability computed live** — never stored.
- **Fixed slot grid** — GCD of service durations. Short bookings never block longer ones.
- **1h booking lead** — no last-minute slots.
- **1h cancel cut-off** — customers can't cancel too late; staff always can.
- **Rate limiting** — login 10/min, register 5/min, reset 3/min.
- **Cascade deletes** — removing a barber removes their hours and bookings.
- **SQLite FK enabled** via PRAGMA so dev matches Postgres.

## Auth

- Passwords: **bcrypt**.
- Login: **JWT** (HS256, 24h, signed with `JWT_SECRET`). Also carries
  `is_admin`/`barber_id` as advisory claims so the frontend can read the
  user's role locally, with no API call — these are never trusted for
  authorization here; every request still re-checks the DB (see
  `get_current_user`/`require_admin` in `security.py`).
- Verification + password-reset: same JWT with a `purpose` claim — not interchangeable.
- Admin console: **session cookies** (same credentials, requires `is_admin`).

## Health probes

- `GET /health` — liveness
- `GET /health/ready` — readiness (DB reachable)
