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
| `REFLEX_API_URL` | Reflex's own event backend URL, used by the browser for websocket state sync **and** the shop logo/favicon (proxied to the backend server-side, see `shop/api.py`) | `http://localhost:8001` |
| `ADMIN_URL` | Admin console link shown to the owner. Optional — leave empty to hide it (e.g. if the backend isn't exposed publicly) | `http://localhost:8000/admin` |
| `MAIL_INBOX_URL` | Dev only: Mailpit link in the verify banner | _(empty)_ |

The booking API itself never needs to be reachable from the browser: the
logo is fetched through Reflex's own already-public backend (`/logo`, mounted
via `api_transformer` in `shop.py`), and email verification links open a
frontend page (`/verify`) that calls the backend server-side — the same
pattern already used for password reset (`/reset-password`).

## Docker

The root `docker-compose.yml` builds and runs this alongside the backend.
See the [root README](../README.md).
