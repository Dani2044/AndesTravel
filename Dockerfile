# Tools API for the Andes Travel agents in watsonx Orchestrate (src/andes/apps/tools_api).
# Built and run by Render (free plan, PORT=8080) on every push to the deploy branch;
# IBM Code Engine (`make api-deploy`) is the alternative.

# --- build: some deps (e.g. zstandard) have no Python 3.15 wheels yet and need a C compiler ---
FROM python:3.15-slim AS build

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

# --- runtime: same base image, no compiler ---
FROM python:3.15-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY --from=build /app /app

RUN useradd --system --uid 10001 app
USER 10001

EXPOSE 8080
CMD ["/app/.venv/bin/uvicorn", "andes.apps.tools_api.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
