# sherlockode

An agent that investigates an organization's Git repositories on your behalf.

Ask a question in natural language; Sherlockode plans an investigation, decides which repositories,
Git operations, provider APIs, analyzers and sandboxed computations it needs, collects evidence, and
answers with conclusions you can trace back to a repository, file, line, commit, API call or command.

```console
# illustrative output
$ sherlockode ask "How many projects use Python < 3.12?" --scope python
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
cp sherlockode.example.toml sherlockode.toml   # edit repositories, providers and groups
cp .env.example .env                            # add ANTHROPIC_API_KEY and provider tokens
docker build -f docker/sandbox.Dockerfile -t sherlockode-sandbox:latest docker

uv run sherlockode repos                  # the catalog, after provider discovery
uv run sherlockode groups                 # logical groups
uv run sherlockode sync --scope backend   # optional: pre-clone repositories
uv run sherlockode ask "Which repositories have not been updated in the last six months?"
uv run sherlockode investigations list
uv run sherlockode investigations show 2026-09-27-001
```

With Docker Compose:

```bash
docker compose --profile build build
DOCKER_GID=$(getent group docker | cut -d: -f3) docker compose run --rm sherlockode ask "Who is the main contributor across our Python repositories?"
```

## Configuration

Precedence, highest first: **environment variables → `.env` → TOML → defaults**.
The TOML file is `./sherlockode.toml`, or the path in `REPO_AGENT_CONFIG` / `--config`.

| Setting                        | Environment variable                        |
|--------------------------------|---------------------------------------------|
| `workspace`                    | `REPO_AGENT_WORKSPACE`                      |
| `log_level`                    | `REPO_AGENT_LOG_LEVEL`                      |
| `sandbox.enabled`              | `REPO_AGENT_SANDBOX__ENABLED`               |
| `agent.model`                  | `REPO_AGENT_AGENT__MODEL`                   |
| `providers.<name>.token`       | `REPO_AGENT_<NAME>_TOKEN` or `REPO_AGENT_PROVIDERS__<NAME>__TOKEN` |
| any nested key                 | `REPO_AGENT_<SECTION>__<KEY>`               |

See [`sherlockode.example.toml`](sherlockode.example.toml) for every section: providers (with MCP
servers), explicit repositories, include/exclude rules, logical groups with selectors, default scope,
agent, limits, sandbox and storage.

Groups are provider independent. A list is shorthand for explicit members; a table can add selectors:

```toml
[groups]
legacy = ["project-x", "project-y"]

[groups.python]
repositories = ["service-a"]
tags = ["python"]            # provider topics or tags from repository definitions
providers = ["gitlab"]
namespaces = ["platform/*"]
patterns = ["*-service"]
```

A question such as *"Which legacy projects are using Python 3.11?"* can be scoped to `legacy` by the
planner, or explicitly with `--scope legacy`.

## Agent tools

| Toolset   | Tools |
|-----------|-------|
| catalog   | `list_repositories`, `list_groups` |
| git       | `sync_repositories`, `git_log`, `git_contributors`, `git_refs`, `list_files`, `search_code`, `read_file`, `commit_activity` |
| provider  | `provider_repository_metadata`, `provider_contributors`, `provider_change_requests`, `provider_issues`, `provider_namespaces`, `provider_api_get` |
| MCP       | `<provider>_mcp_*`, from the provider's MCP server when enabled |
| analysis  | `run_analyzer` (`languages`, `python_versions`, `dependencies`) |
| sandbox   | `run_in_sandbox` (when the sandbox is enabled) |
| evidence  | `record_evidence` |

## Development

```bash
uv sync
uv run pytest
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy src
SHERLOCKODE_SANDBOX_IMAGE=sherlockode-sandbox:latest uv run pytest tests/test_sandbox.py   # Docker isolation test
```

Architecture, extension points and design decisions: [`docs/architecture.md`](docs/architecture.md).
