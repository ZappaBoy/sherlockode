# Agent backends

`agent.backend` (see [`configuration.md`](configuration.md#agent-agent)) selects how the investigating
agent is driven. See [`architecture.md`](architecture.md#agent-backends) for how each backend fits
into the investigation lifecycle.

## `pydantic-ai` (default): Anthropic or OpenAI

In-process agent, full planner + investigator + native/MCP toolsets.

```toml
[agent]
backend = "pydantic-ai"
model = "anthropic:claude-opus-5-5"         # or "anthropic:claude-sonnet-5", "anthropic:claude-haiku-4-5"
planner_model = "anthropic:claude-sonnet-5"  # optional: cheaper model for planning
```

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-...
```

For an OpenAI model instead, use an `openai:` prefixed model string and set `OPENAI_API_KEY`:

```toml
[agent]
model = "openai:gpt-5"
```

## `pydantic-ai`: local LLM via an OpenAI-compatible API

Any server that speaks the OpenAI chat-completions API works: Ollama, vLLM, LM Studio, llama.cpp
server, LiteLLM. Set `base_url`; `model` is the name/tag the server itself knows.

```toml
[agent]
backend = "pydantic-ai"
model = "qwen2.5-coder:32b"
base_url = "http://localhost:11434/v1"     # Ollama's OpenAI-compatible endpoint
# api_key_env = "LOCAL_LLM_API_KEY"        # only if the server checks the key
```

```bash
# .env — most local servers accept any value or no key at all
# LOCAL_LLM_API_KEY=not-needed
```

Running Sherlockode itself in Docker: `localhost` inside the container is the container, not the
host. Point `base_url` at the Docker host instead:

```toml
[agent]
base_url = "http://host.docker.internal:11434/v1"
```

```yaml
# compose.yaml, on Linux only (Docker Desktop provides host.docker.internal already)
services:
  sherlockode:
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

## `claude-code`: Claude Code CLI

Skips the planner; runs read-only over the checked-out repositories using the CLI's own tool loop
(`claude -p ... --output-format json --allowedTools Read,Grep,Glob,Bash(git log:*),Bash(git
show:*),Bash(git diff:*),Bash(git blame:*) --permission-mode bypassPermissions`).

```toml
[agent]
backend = "claude-code"
model = "claude-opus-5-5"      # optional; omit to use the CLI's own default
# cli_command = "/usr/local/bin/claude"   # override the binary path
# cli_args = []
cli_timeout_seconds = 600
```

Authenticate the CLI itself, not Sherlockode:

```bash
claude login          # caches credentials under ~/.claude
# or
export ANTHROPIC_API_KEY=sk-ant-...
```

In Docker, mount the cached login or pass the key through `.env` — see the README's
[Docker section](../README.md#credentials-for-the-cli-backends-in-docker).

## `codex`: Codex CLI

Skips the planner; runs read-only via `codex exec --sandbox read-only --skip-git-repo-check
--output-last-message <file>`.

```toml
[agent]
backend = "codex"
model = "gpt-5-codex"          # optional; omit to use the CLI's own default
cli_timeout_seconds = 600
```

Authenticate the CLI itself:

```bash
codex login            # caches credentials under ~/.codex
# or
export OPENAI_API_KEY=sk-...
```

Do not add `--full-auto` to `agent.cli_args`: Sherlockode always invokes Codex with
`--sandbox read-only`, and `--full-auto` conflicts with an explicit `--sandbox` flag. Any extra flags
in `cli_args` are appended after the built-in ones and before the prompt argument.

## Common notes

- Both CLI backends require the CLI binary (and, for Claude Code, Node.js) to be present in the
  environment `sherlockode` runs in. The application Docker image only installs them when built with
  `--build-arg INSTALL_AGENT_CLIS=true` (see the README's [Docker section](../README.md#docker)).
- `agent.instructions` (extra organization-specific guidance) and the environment description
  (scope, groups, providers, analyzers, sandbox status) are included in both the PydanticAI prompts and
  the CLI prompt — see [`architecture.md`](architecture.md#prompts).
- `agent.temperature` and `agent.planning`/`--plan`/`--no-plan` only affect the `pydantic-ai` backend.
