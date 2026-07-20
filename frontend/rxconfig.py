import os

import reflex as rx

# Reflex's production mode (`reflex run --env prod`, used by the Dockerfile)
# refuses to start if frontend_port != backend_port — it needs a single port
# to serve the page and its own event backend (websocket state, uploads,
# our /logo proxy — see shop/api.py) together. The Dockerfile sets
# REFLEX_SINGLE_PORT=1 so the container (docker-compose and Kubernetes both
# run this same image) unifies onto port 3000. Plain local dev (`uv run
# reflex run`, no Docker) keeps the original two-port split — dev mode runs
# separate frontend/backend dev servers that can't actually share a port,
# unlike prod's single combined server.
_single_port = os.environ.get("REFLEX_SINGLE_PORT") == "1"

# REFLEX_API_URL: where the *browser* reaches the backend (websocket state
# sync, uploads, /logo). Locally this is inferred automatically. Behind an
# Ingress/reverse proxy (e.g. Kubernetes) there's no bare port to connect
# to, so set this to the public https URL that routes to the frontend
# Service — see charts/README.md.
_api_url = os.environ.get("REFLEX_API_URL", "")

config = rx.Config(
    app_name="shop",
    frontend_port=3000,
    backend_port=3000 if _single_port else 8001,
    **({"api_url": _api_url} if _api_url else {}),
    plugins=[
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(
                appearance="light",
                accent_color="bronze",
                gray_color="sand",
                radius="large",
            )
        ),
        rx.plugins.SitemapPlugin(),
    ],
)
