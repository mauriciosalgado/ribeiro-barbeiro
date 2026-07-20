# The Reflex booking UI. Builds the frontend and serves it alongside the
# small event backend the browser talks to.
FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl unzip \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"

# Install dependencies first (cached until the lockfile changes), then the app.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .

EXPOSE 3000
# Production mode serves the pre-built static frontend instead of running
# Vite's dev server — the dev server enforces an "allowed hosts" allow-list
# that blocks any Host header other than localhost, which would 403 every
# request once this sits behind a real Ingress/domain. --single-port merges
# the page and Reflex's own backend (websocket state, /_upload, our /logo
# proxy) onto the one port configured in rxconfig.py (frontend_port ==
# backend_port); Reflex's production mode requires this flag whenever a
# single port is used.
CMD ["reflex", "run", "--env", "prod", "--single-port"]
