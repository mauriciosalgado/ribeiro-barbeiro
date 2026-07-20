import os

import reflex as rx

# The compile-time default theme; the owner's saved colours arrive at runtime and
# are published as CSS variables that re-theme the whole page (see shop/shop.py).
# The dev server's event backend runs on 8001 so it doesn't clash with the API.
#
# REFLEX_API_URL: where the *browser* reaches Reflex's own event backend
# (websocket state sync, uploads — a different thing from our FastAPI API).
# Locally this is inferred as http://localhost:8001 automatically. Behind an
# ingress/reverse proxy (e.g. Kubernetes) there's no bare port to connect to,
# so set this to the public https URL that routes /_event, /_upload, /ping,
# /_health, /_all_routes to the frontend's backend port — see k8s/README.md.
_api_url = os.environ.get("REFLEX_API_URL", "")

config = rx.Config(
    app_name="shop",
    frontend_port=3000,
    backend_port=8001,
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
