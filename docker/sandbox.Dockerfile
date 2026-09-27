# Image for disposable sandbox containers that run agent-generated analysis code.
FROM python:3.12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ripgrep jq ca-certificates coreutils \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir packaging pyyaml tomli-w \
    && git config --system --add safe.directory '*'
USER 65534:65534
WORKDIR /work
