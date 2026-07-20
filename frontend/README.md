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
| `API_URL` | Backend URL (server-side) | `http://localhost:8000` |
| `PUBLIC_API_URL` | Backend URL the browser uses (logo, favicon) | same as `API_URL` |
| `ADMIN_URL` | Admin console link shown to the owner | `http://localhost:8000/admin` |
| `MAIL_INBOX_URL` | Dev only: Mailpit link in the verify banner | _(empty)_ |

## Docker

The root `docker-compose.yml` builds and runs this alongside the backend.
See the [root README](../README.md).
