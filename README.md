# sherlockcode

An agent that investigates an organization's Git repositories on your behalf.

Ask a question in natural language; Sherlockcode plans an investigation, decides which repositories,
Git operations, provider APIs, analyzers and sandboxed computations it needs, collects evidence, and
answers with conclusions you can trace back to a repository, file, line, commit, API call or command.

```console
# illustrative output
$ sherlockcode ask "How many projects use Python < 3.12?" --scope python
# Investigation 2026-09-27-001

**Question:** How many projects use Python < 3.12?

## Answer
2 of 5 Python repositories declare a minimum Python version below 3.12.

## Findings
- [observed] service-a requires Python >=3.11
  - `E0004` pyproject.toml declares Python >=3.11 — service-a pyproject.toml:3 @1f2e3d4c5b6a
- [computed] service-c pins a python:3.10 base image while CI tests 3.12
  ...
```

## Features

- **Natural language first** — no query language; a PydanticAI agent plans and runs the investigation.
- **Provider agnostic** — generic Git, GitHub and GitLab out of the box; new providers plug into a registry.
- **Native tools or MCP** — provider APIs reach the agent through built-in tools, the provider's official
  MCP server, or both, selected per provider in configuration.
- **Flexible agent backends** — an in-process PydanticAI agent against any cloud or local model, or the
  official Claude Code / Codex CLIs driven non-interactively and read-only.
- **Evidence over assertions** — every tool result is recorded with an evidence id; findings are
  classified as *observed*, *computed* or *inferred* and must cite evidence.
- **Reproducible** — each investigation stores its manifest, redacted configuration, plan, step trace,
  evidence ledger, sandbox runs and report under `workspace/investigations/<id>/`.
- **Secure by default** — repository hooks never run; agent-generated code runs in disposable,
  network-less, read-only, non-root, resource-limited containers.
- **Configuration without code** — TOML + `.env` + environment variables with explicit precedence.
- **Container first** — one Docker image for the application, one for the sandbox.

## Quick start

```bash
uv sync
cp sherlockcode.example.toml sherlockcode.toml   # edit repositories, providers, groups and agent backend
cp .env.example .env                            # add ANTHROPIC_API_KEY / OPENAI_API_KEY and provider tokens
docker build -f docker/sandbox.Dockerfile -t sherlockcode-sandbox:latest docker   # or `docker compose --profile build build`

uv run sherlockcode repos                  # the catalog, after provider discovery
uv run sherlockcode groups                 # logical groups
uv run sherlockcode sync --scope backend   # optional: pre-clone repositories
uv run sherlockcode ask "Which repositories have not been updated in the last six months?"
uv run sherlockcode investigations list
uv run sherlockcode investigations show 2026-09-27-001
```

## Configuration

Precedence, highest first: **environment variables → `.env` → TOML → defaults**.
The TOML file is `./sherlockcode.toml`, or the path in `REPO_AGENT_CONFIG` / `--config`.

Any setting can be overridden with `REPO_AGENT_<SECTION>__<KEY>` (nested keys use a double
underscore, e.g. `REPO_AGENT_SANDBOX__MEMORY=2g`, `REPO_AGENT_AGENT__BASE_URL=...`). Provider tokens
also accept the shorthand `REPO_AGENT_<PROVIDER NAME>_TOKEN` (e.g. `REPO_AGENT_GITHUB_TOKEN`,
`REPO_AGENT_GITLAB_TOKEN`) instead of `REPO_AGENT_PROVIDERS__<NAME>__TOKEN`.

| Setting                   | Environment variable                                               |
|----------------------------|---------------------------------------------------------------------|
| `workspace`                | `REPO_AGENT_WORKSPACE`                                              |
| `log_level`                | `REPO_AGENT_LOG_LEVEL`                                              |
| `sandbox.enabled`          | `REPO_AGENT_SANDBOX__ENABLED`                                       |
| `agent.backend`            | `REPO_AGENT_AGENT__BACKEND`                                         |
| `agent.model`              | `REPO_AGENT_AGENT__MODEL`                                           |
| `providers.<name>.token`   | `REPO_AGENT_<NAME>_TOKEN` or `REPO_AGENT_PROVIDERS__<NAME>__TOKEN`  |
| any nested key             | `REPO_AGENT_<SECTION>__<KEY>`                                       |

The full reference of every key, type, default and environment variable is in
[`docs/configuration.md`](docs/configuration.md). Architecture and design decisions are in
[`docs/architecture.md`](docs/architecture.md). Agent backend setup is detailed in
[`docs/agent-backends.md`](docs/agent-backends.md).

See [`sherlockcode.example.toml`](sherlockcode.example.toml) for a complete, commented example of every
section below.

### Repository selection

Repositories come from two independent sources that are merged: **provider discovery** (per-provider,
via `providers.<name>.discovery`) and **explicit entries** (`[repositories] include`). Every mode below
supports selective ignoring, both per provider (`providers.<name>.exclude`) and globally
(`[repositories] exclude`); glob patterns are matched against the repository name, full path and URL.

**(a) All repositories on a provider** the token can access:

```toml
[providers.gitlab]
kind = "gitlab"
token = ""                       # or REPO_AGENT_GITLAB_TOKEN
discovery = "all"                # every project the token can see
exclude = ["*-archive", "sandbox-*"]   # ignored even though discovery finds them
```

**(b) All repositories of specific groups/orgs** (`namespaces`):

```toml
[providers.github]
kind = "github"
namespaces = ["my-org", "another-org"]   # discovery defaults to "namespaces" when namespaces is set
# discovery = "namespaces"               # equivalent, explicit
exclude = ["*-deprecated"]

[providers.gitlab]
kind = "gitlab"
namespaces = ["platform"]                # groups, including subgroups
discovery = "namespaces"
```

**(c) Only specific repositories**, ignoring provider discovery entirely:

```toml
[repositories]
mode = "explicit"                        # disables discovery on every provider, regardless of their settings
include = [
    "git@gitlab.example.com:platform/service-a.git",
    "https://github.com/example/service-b.git",
    { url = "https://git.example.org/legacy/project-x.git", name = "project-x", tags = ["legacy"] },
]
exclude = ["*-archive"]                  # still applies, e.g. if a glob later matches an added entry
```

`mode = "auto"` (the default) instead lets each provider discover per its own `discovery` setting,
*and* still honors `[repositories] include`/`exclude` — so you can mix discovery with a few explicit
extra repositories (e.g. one hosted outside any configured provider) at the same time.

### Logical groups

Groups are provider-independent and can be scoped with `--scope <group>` or used in
`agent.default_scope`. A list is shorthand for explicit members; a table can add selectors, matched
as a union with any explicit `repositories`:

```toml
[groups]
legacy = ["project-x", "project-y"]

[groups.python]
repositories = ["service-a"]
tags = ["python"]            # provider topics/tags, or tags from an explicit repository definition
providers = ["gitlab"]
namespaces = ["platform/*"]
patterns = ["*-service"]      # glob against name, full path and URL
```

A question such as *"Which legacy projects are using Python 3.11?"* can be scoped to `legacy` by the
planner, or explicitly with `--scope legacy`.

### Agent backends

`agent.backend` selects how the investigating agent runs. The CLI backends (`claude-code`, `codex`)
**skip the planner** and run **read-only**, iterating over the checked-out repositories with the
official CLI's own tool loop instead of Sherlockcode's native/MCP toolsets.

**Anthropic or OpenAI via PydanticAI** (the default backend, in-process):

```toml
[agent]
backend = "pydantic-ai"
model = "anthropic:claude-opus-5-5"        # or "anthropic:claude-sonnet-5", "anthropic:claude-haiku-4-5"
planner_model = "anthropic:claude-sonnet-5" # optional, cheaper model for the planning phase
```

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-...
# or, for an OpenAI model:
# OPENAI_API_KEY=sk-...
```

**Local LLM via an OpenAI-compatible API** (Ollama, vLLM, LM Studio, llama.cpp server, LiteLLM), still
the `pydantic-ai` backend:

```toml
[agent]
backend = "pydantic-ai"
model = "qwen2.5-coder:32b"           # the model name/tag as the local server knows it
base_url = "http://localhost:11434/v1"  # Ollama; vLLM/LM Studio expose the same OpenAI-compatible path
# api_key_env = "LOCAL_LLM_API_KEY"   # only if your server checks the key; most local servers need none
```

When Sherlockcode itself runs in Docker, `localhost` refers to the container, not the host: point
`base_url` at `http://host.docker.internal:11434/v1` and, on Linux, add to `compose.yaml`:

```yaml
services:
  sherlockcode:
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

**Claude Code CLI** (skips the planner, read-only, uses `claude`'s own tools):

```toml
[agent]
backend = "claude-code"
model = "claude-opus-5-5"        # optional; omit to use the CLI's own default
# cli_command = "/usr/local/bin/claude"
# cli_args = []
cli_timeout_seconds = 600
```

Authenticate the CLI itself before running Sherlockcode: either `claude login` once (credentials are
cached under `~/.claude`) or set `ANTHROPIC_API_KEY` in the environment the CLI runs in.

**Codex CLI** (skips the planner, read-only, uses `codex exec --sandbox read-only`):

```toml
[agent]
backend = "codex"
model = "gpt-5-codex"            # optional; omit to use the CLI's own default
cli_timeout_seconds = 600
```

Authenticate with `codex login` (cached under `~/.codex`) or `OPENAI_API_KEY` in the environment. Do
not add `--full-auto` to `agent.cli_args`: Sherlockcode always invokes Codex with
`--sandbox read-only`, and `--full-auto` conflicts with that flag.

## CLI usage

```bash
sherlockcode [--config PATH] ask "<question>" [--scope NAME ...] [--plan|--no-plan] [--json]
sherlockcode [--config PATH] repos [--scope NAME ...]
sherlockcode [--config PATH] groups
sherlockcode [--config PATH] sync [--scope NAME ...]
sherlockcode [--config PATH] config
sherlockcode [--config PATH] investigations list
sherlockcode [--config PATH] investigations show <investigation-id>
```

- `--config` / `REPO_AGENT_CONFIG` selects the TOML file (default `./sherlockcode.toml`).
- `ask` investigates a question and prints an evidence-backed Markdown (or `--json`) report; the full
  investigation is also saved under `workspace/investigations/<id>/`.
- `repos` lists the resolved catalog (name, provider, full path, tags, whether it is cloned yet),
  optionally restricted with `--scope` (repeatable; group or repository name).
- `groups` lists logical groups and their resolved members.
- `sync` clones missing repositories and fetches existing checkouts, optionally restricted with
  `--scope`.
- `config` prints the effective, fully-merged configuration with secrets redacted.
- `investigations list` / `investigations show <id>` browse past investigations stored in the
  workspace.

## Docker

Two images are involved: the **application image** (built from the root `Dockerfile`) and the
**sandbox image** (`docker/sandbox.Dockerfile`) used to run agent-generated analysis code. Neither the
repositories under investigation nor their hooks ever run outside the sandbox.

### Build

```bash
docker compose --profile build build
# equivalent to:
docker build -t sherlockcode:latest .
docker build -f docker/sandbox.Dockerfile -t sherlockcode-sandbox:latest docker
```

To include the Claude Code and Codex CLIs in the application image (required for `backend =
"claude-code"` / `"codex"`), build with `INSTALL_AGENT_CLIS=true`:

```bash
docker build --build-arg INSTALL_AGENT_CLIS=true -t sherlockcode:latest .
# or, with compose (compose.yaml reads it from the environment):
INSTALL_AGENT_CLIS=true docker compose --profile build build sherlockcode
```

### Prepare configuration

```bash
cp sherlockcode.example.toml sherlockcode.toml
cp .env.example .env
```

### Run with Docker Compose

```bash
docker compose --profile build build   # once, or after changing the Dockerfiles

DOCKER_GID=$(getent group docker | cut -d: -f3) \
  docker compose run --rm sherlockcode repos

DOCKER_GID=$(getent group docker | cut -d: -f3) \
  docker compose run --rm sherlockcode sync --scope backend

DOCKER_GID=$(getent group docker | cut -d: -f3) \
  docker compose run --rm sherlockcode ask "Who is the main contributor across our Python repositories?"

DOCKER_GID=$(getent group docker | cut -d: -f3) \
  docker compose run --rm sherlockcode investigations list
```

`compose.yaml` mounts `./workspace` and `./sherlockcode.toml`, loads `.env`, and mounts the host Docker
socket so the container can start sandbox containers on the host daemon (Docker-out-of-Docker).
`DOCKER_GID` adds the container user to the host's `docker` group so it can use that socket; on a
rootless Docker install this is usually unnecessary. `REPO_AGENT_SANDBOX__HOST_WORKSPACE` (already set
in `compose.yaml` to `${PWD}/workspace`) tells the sandbox code how to translate the container's
`/workspace` paths into host paths for the bind mounts it asks the host daemon to create — without it,
sandbox runs started from inside the container would try to bind-mount container-internal paths on
the host and fail.

### Run with plain `docker run`

```bash
docker run --rm -it \
  --env-file .env \
  -e REPO_AGENT_SANDBOX__HOST_WORKSPACE="$PWD/workspace" \
  -v "$PWD/workspace:/workspace" \
  -v "$PWD/sherlockcode.toml:/config/sherlockcode.toml:ro" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --group-add "$(getent group docker | cut -d: -f3)" \
  sherlockcode:latest ask "Which repositories have not been updated in the last six months?"
```

### Credentials for the CLI backends in Docker

Mount the CLI's cached login (created by running `claude login` / `codex login` on the host) into the
container's home directory (`sherlock`, uid `10001`), or pass an API key through `.env` instead:

```bash
docker run --rm -it \
  --env-file .env \
  -v "$PWD/workspace:/workspace" \
  -v "$PWD/sherlockcode.toml:/config/sherlockcode.toml:ro" \
  -v "$HOME/.claude:/home/sherlock/.claude" \
  -v "$HOME/.codex:/home/sherlock/.codex" \
  sherlockcode:latest ask "..."
```

or, in `compose.yaml`, add under `services.sherlockcode.volumes`:

```yaml
      # - ~/.claude:/home/sherlock/.claude
      # - ~/.codex:/home/sherlock/.codex
```

### Local LLM in Docker

```bash
# sherlockcode.toml
# [agent]
# base_url = "http://host.docker.internal:11434/v1"
```

```yaml
# compose.yaml
services:
  sherlockcode:
    extra_hosts:
      - "host.docker.internal:host-gateway"   # required on Linux; Docker Desktop provides it already
```

### Security notes

- Agent-generated code never runs on the host: it runs in a disposable `sherlockcode-sandbox` container
  per execution, with `--network none`, a read-only root filesystem, the repository mounted read-only,
  `--cap-drop ALL`, `no-new-privileges`, a non-root user, and CPU/memory/PID limits (see
  [`docs/architecture.md`](docs/architecture.md#security-boundaries)).
- Mounting `/var/run/docker.sock` into the application container grants it control of the host Docker
  daemon, which is root-equivalent. Prefer rootless Docker, a remote Docker host (`DOCKER_HOST`), or a
  dedicated sandbox host in production. `sandbox.enabled = false` removes code execution from the agent
  entirely; `sandbox.backend = "local"` avoids Docker-out-of-Docker but provides no real isolation and
  is for development only.
- Repository Git hooks are never executed; provider tokens and CLI credentials are only as exposed as
  the volumes/env vars you choose to mount.

## Development

```bash
uv sync
uv run pytest
uv run ruff check sherlockcode tests && uv run ruff format --check sherlockcode tests
uv run mypy sherlockcode
SHERLOCKCODE_SANDBOX_IMAGE=sherlockcode-sandbox:latest uv run pytest tests/test_sandbox.py   # Docker isolation test
```

## Project layout

```text
sherlockcode/
├── cli.py                 Typer CLI (ask, repos, groups, sync, config, investigations)
├── app.py                 Composition root: wires settings, providers, workspace, git, sandbox
├── config/                Pydantic settings: TOML + .env + environment, config section models
├── domain/                Provider-independent models: repositories, commits, work items, evidence
├── git/                   Async git CLI client, hardened against repository-provided hooks/helpers
├── providers/             Provider base + capability mixins, GitHub, GitLab, generic Git, MCP, registry
├── catalog/               Repository catalog: explicit + discovered repos, include/exclude, groups, scope
├── workspace/              On-disk layout and checkout management
├── analysis/               Deterministic, read-only analyzers (languages, python_versions, dependencies)
├── sandbox/                Execution sandbox: Docker (default) and local (development only)
├── agent/                  Agent backends, instructions, dependencies and toolsets
│   ├── backend.py          PydanticAI backend and Claude Code / Codex CLI backends
│   ├── factory.py          Builds the PydanticAI investigator/planner agents and toolsets
│   ├── toolsets/           Native tool implementations (catalog, git, provider, analysis, evidence, recording)
│   └── prompts/            Prompt rendering
│       └── templates/      Jinja templates: investigator, planner, environment, investigation_prompt, cli_agent
└── investigation/          Lifecycle service, recorder (trace + evidence ledger), models, rendering
```
