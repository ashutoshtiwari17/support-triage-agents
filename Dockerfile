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

# The app runs as an unprivileged user. --chown makes that user the owner of
# the code, so it can read the files whatever permissions they had on the
# machine that built the image.
RUN useradd --create-home app && mkdir -p /app/runs && chown app:app /app/runs
COPY --chown=app:app agents ./agents
COPY --chown=app:app core ./core
COPY --chown=app:app web ./web
COPY --chown=app:app server.py main.py ./
USER app

# Cloud Run tells the container which port to listen on through $PORT
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080}"]
