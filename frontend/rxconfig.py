import os

import reflex as rx

# Reflex serves the page and its own event backend (websocket state sync,
# uploads, and our /logo proxy — see shop/api.py) from a SINGLE port. This
# isn't a style choice: Reflex's production mode (`reflex run --env prod`,
# used by the Dockerfile) refuses to start if frontend_port != backend_port,
# since --single-port merges them. Keeping them equal in dev too means the
# same config works unchanged in both docker-compose and Kubernetes.
#
# REFLEX_API_URL: where the *browser* reaches this same port (websocket
# state sync, uploads, /logo). Locally this is inferred as
# http://localhost:3000 automatically. Behind an Ingress/reverse proxy
# (e.g. Kubernetes) there's no bare port to connect to, so set this to the
# public https URL that routes to the frontend Service — see charts/README.md.
_api_url = os.environ.get("REFLEX_API_URL", "")

config = rx.Config(
    app_name="shop",
    frontend_port=3000,
    backend_port=3000,
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
