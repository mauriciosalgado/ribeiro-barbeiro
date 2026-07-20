"""Extra HTTP routes mounted on Reflex's own backend.

Reflex already runs a small public FastAPI app for its own event
backend (websocket state sync, uploads — see rxconfig.py's REFLEX_API_URL).
Mounting routes here lets the browser fetch things it needs directly, like
the shop's logo, without the booking API itself ever having to be reachable
from the internet — only the frontend does.
"""

import httpx
from fastapi import FastAPI, Response

from shop.state import API_URL

api = FastAPI()


@api.get("/logo")
async def logo() -> Response:
    """Proxy the shop's logo from the booking API (server-side, internal call)."""
    async with httpx.AsyncClient(base_url=API_URL, timeout=5) as client:
        upstream = await client.get("/settings/logo")
    return Response(
        content=upstream.content,
        media_type=upstream.headers.get("content-type", "image/jpeg"),
        headers={"Cache-Control": upstream.headers.get("cache-control", "no-cache")},
    )
