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

EXPOSE 3000 8001
# Reflex's production mode expects a single port behind a reverse proxy. Until we
# add one, run the built-in server (compiles the UI on first start).
CMD ["reflex", "run"]
