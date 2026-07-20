# Build the virtualenv with uv, then copy it into a slim runtime image.
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Install dependencies first (cached until the lockfile changes), then the app.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY . .
RUN uv sync --frozen --no-dev


FROM python:3.13-slim

WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"

# Run as an unprivileged user. Pre-create the data dir so the mounted volume
# inherits this ownership and SQLite can write its database file there.
RUN useradd --create-home app \
    && mkdir -p /data \
    && chown -R app:app /app /data
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
