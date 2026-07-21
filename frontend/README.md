# Frontend

Booking website built with [Reflex](https://reflex.dev) — pure Python, no
HTML/JS/CSS files. Compiles to a React app served to the browser.

## Layout

```
shop/
├── shop.py    page shell: navbar, hero, layout, colour-mode driver
├── state.py   page state + API communication
├── views.py   UI components: auth, booking, barber agenda, admin panel
└── ui.py      design system: palette derivation, reusable pieces
rxconfig.py    Reflex config (ports, theme)
```

## How it works

One page that adapts to who's signed in:

| Role | View |
| ---- | ---- |
| Signed out | Login/register with configurable headline |
| Customer | Barber → service → day → slot → book. Plus their appointments. |
| Barber | Agenda, working hours editor, services editor |
| Owner | All of the above + branding controls + admin console link |

The owner picks two colours (brand + background); the rest of the palette is
derived at runtime via CSS variables.

## Run locally

The backend must be running (see `../backend/`).

```bash
uv sync
API_URL=http://localhost:8000 uv run reflex run
```

Website → http://localhost:3000

## Configuration

| Variable | Purpose | Default |
| -------- | ------- | ------- |
| `API_URL` | Backend URL (server-side calls only — never reaches the browser) | `http://localhost:8000` |
| `JWT_SECRET` | Must match the backend's `JWT_SECRET` exactly. Lets the frontend verify an access token's signature locally (no API call) to know the user's role immediately on page load — see "Fast auth on load" below | _(required)_ |
| `REFLEX_API_URL` | Reflex's own backend URL, used by the browser for websocket state sync **and** the shop logo/favicon (proxied to the backend server-side, see `shop/api.py`) | `http://localhost:3000` |
| `ADMIN_URL` | Public URL of the backend's SQLAdmin console, shown as a link to the owner. Empty (default) hides the link. **Setting this only makes sense if the backend itself is also reachable from the internet at that URL** — this variable doesn't expose anything by itself, it just links to wherever you've already made `/admin` public | `http://localhost:8000/admin` |
| `MAIL_INBOX_URL` | Dev only: Mailpit link in the verify banner | _(empty)_ |

The booking API itself never needs to be reachable from the browser: the
logo is fetched through Reflex's own already-public backend (`/logo`, mounted
via `api_transformer` in `shop.py`), and email verification links open a
frontend page (`/verify`) that calls the backend server-side — the same
pattern already used for password reset (`/reset-password`). The **only**
reason to expose the backend publicly at all is wanting the SQLAdmin console
or interactive API docs reachable from a plain browser; nothing customers do
(booking, verifying email, resetting a password) requires it.

## Fast auth on load

Reflex is a single-page app: every `State` field starts at its Python-class
default on each fresh page load, and only gets corrected once the WebSocket
connects and an `on_load` handler (`init()`, `refresh()`) finishes. Without
help, that means a page reload always shows the wrong thing for a moment —
a login form for someone already signed in, or the wrong role's dashboard —
until a full round-trip to the backend (`/auth/me`, `/barbers/me`, ...)
comes back.

To avoid that, the access token carries `is_admin`/`barber_id` as claims
(see `backend/app/security.py`). `state.py`'s `refresh()` verifies the
token's signature and reads those claims **locally, with no network
call**, as its very first step — before doing anything else — and only
then flips `State.ui_ready` to `True`. `login()` does the same right after
a successful sign-in, so `token`/`is_admin`/`barber_id` all land in the
same state update instead of `is_admin`/`barber_id` trailing a step behind
(which would otherwise flash the wrong role for an instant — Reflex sends
one state update per event/`yield`, so anything not set before that point
literally cannot be part of the same update, per Reflex's own event model).
The slower, authoritative calls to the backend still happen right after —
they can only correct a stale/tampered claim, never grant access the
backend wouldn't have granted anyway (every real request is re-checked
against the database regardless of what the token claims).

Until `ui_ready` is `True`, `shop.py`'s `index()` renders nothing but a
blank white box — no skeleton, no spinner — since anything more specific
risks briefly showing the wrong content, which is worse than a blank page.

## Docker

The root `docker-compose.yml` builds and runs this alongside the backend.
See the [root README](../README.md).
