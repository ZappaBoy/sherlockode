# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.8 AS uv
FROM docker:28-cli AS docker-cli

FROM python:3.12-slim AS build
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client ca-certificates ripgrep util-linux tzdata \
    && rm -rf /var/lib/apt/lists/*
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=build /app/.venv /app/.venv
RUN useradd --create-home --uid 10001 sherlock \
    && mkdir -p /workspace /config \
    && chown sherlock:sherlock /workspace
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    REPO_AGENT_WORKSPACE=/workspace \
    REPO_AGENT_CONFIG=/config/sherlockode.toml
USER sherlock
WORKDIR /workspace
VOLUME ["/workspace"]
ENTRYPOINT ["sherlockode"]
CMD ["--help"]
