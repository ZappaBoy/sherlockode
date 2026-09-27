# sherlockode

An agentic repository intelligence platform for querying, analyzing, and comparing software repositories with natural language.

## Current architecture scaffold

This repository contains a minimal Python scaffold for the platform's core architecture:

- Pydantic domain models for repositories, providers, groups, execution limits, sandbox, and workspace settings
- Investigation models with explicit evidence typing (`observed`, `computed`, `inferred`)
- Provider abstraction interfaces and registry for pluggable Git, GitHub, and GitLab adapters
- TOML configuration loading with environment-variable override precedence (`env > TOML > defaults`)
- Workspace manager that creates first-class investigation directories (`repositories/`, `investigations/`, `artifacts/`, `cache/`)

## Configuration precedence

`AppConfig.load()` implements this precedence order:

1. Environment variables
2. TOML configuration
3. Application defaults

Supported environment overrides include:

- `REPO_AGENT_GITHUB_TOKEN`
- `REPO_AGENT_GITLAB_TOKEN`
- `REPO_AGENT_WORKSPACE`
- `REPO_AGENT_SANDBOX_ENABLED`
- `REPO_AGENT_LOG_LEVEL`
- `REPO_AGENT_USE_MCP_SERVERS`

## Development

```bash
pip install -e .
python -m unittest discover -s tests
```
