# Container image for Cloud Run (or any Docker host).
FROM python:3.12-slim

# uv installs the exact versions pinned in uv.lock
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Dependencies first, so this layer is reused when only the code changes
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY agents ./agents
COPY core ./core
COPY web ./web
COPY server.py main.py ./

# Run as an unprivileged user; it only needs to write run files
RUN useradd --create-home app && mkdir -p /app/runs && chown -R app /app/runs
USER app

# Cloud Run tells the container which port to listen on through $PORT
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080}"]
