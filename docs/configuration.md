# Configuration reference

Settings are loaded by `sherlockode.config.settings.Settings` (pydantic-settings). Precedence, highest
first: **environment variables → `.env` → TOML file → defaults**. Nested keys use `__` as the
environment variable delimiter (e.g. `REPO_AGENT_SANDBOX__ENABLED=false`). The TOML file is
`./sherlockode.toml`, or the path given by `REPO_AGENT_CONFIG` / `--config`. Every section rejects
unknown keys (`extra="forbid"`), so a typo fails at startup instead of being silently ignored.

Provider tokens additionally accept the shorthand `REPO_AGENT_<PROVIDER NAME>_TOKEN` (uppercased,
`-` replaced with `_`), e.g. `REPO_AGENT_GITHUB_TOKEN`, instead of
`REPO_AGENT_PROVIDERS__<NAME>__TOKEN`. A `git` provider is always present even if not configured
explicitly (used for repositories with no matching host).

Secrets (`SecretStr` fields) are redacted by `sherlockode config` and in investigation manifests.

## Top level

| Key           | Type            | Default                | Environment variable       | Description |
|---------------|-----------------|-------------------------|-----------------------------|--------------|
| `workspace`   | `Path`          | `workspace`             | `REPO_AGENT_WORKSPACE`      | Root directory for repository checkouts, investigations and artifacts. |
| `log_level`   | `str`           | `INFO`                  | `REPO_AGENT_LOG_LEVEL`      | Python logging level. |
| `providers`   | `dict[str, ProviderConfig]` | `{}` (plus an implicit `git` entry) | `REPO_AGENT_PROVIDERS__<NAME>__<KEY>` | Named provider configurations; see [Providers](#providers-providersname). |
| `repositories`| `RepositoriesConfig` | see below         | `REPO_AGENT_REPOSITORIES__<KEY>` | Explicit repositories and global include/exclude/mode; see [Repositories](#repositories-repositories). |
| `groups`      | `dict[str, GroupDefinition]` | `{}`     | `REPO_AGENT_GROUPS__<NAME>__<KEY>` | Logical, provider-independent repository groups; see [Groups](#groups-groupsname). |
| `agent`       | `AgentConfig`   | see below               | `REPO_AGENT_AGENT__<KEY>`   | Investigating agent backend and model; see [Agent](#agent-agent). |
| `sandbox`     | `SandboxConfig` | see below               | `REPO_AGENT_SANDBOX__<KEY>` | Execution sandbox for agent-generated code; see [Sandbox](#sandbox-sandbox). |
| `limits`      | `LimitsConfig`  | see below               | `REPO_AGENT_LIMITS__<KEY>`  | Resource and usage limits; see [Limits](#limits-limits). |
| `storage`     | `StorageConfig` | see below               | `REPO_AGENT_STORAGE__<KEY>` | Investigation retention; see [Storage](#storage-storage). |

## Providers (`providers.<name>`)

`ProviderConfig`:

| Key                | Type                        | Default        | Environment variable | Description |
|--------------------|------------------------------|-----------------|------------------------|--------------|
| `kind`             | `str`                       | *required*      | `REPO_AGENT_PROVIDERS__<NAME>__KIND` | Provider implementation registered in the provider registry: `git`, `github`, `gitlab` (more can be registered). |
| `base_url`         | `str \| None`                | `None`          | `REPO_AGENT_PROVIDERS__<NAME>__BASE_URL` | API base URL; defaults to the provider's public API (`https://api.github.com`, `https://gitlab.com/api/v4`). |
| `token`            | `SecretStr \| None`          | `None`          | `REPO_AGENT_<NAME>_TOKEN` or `REPO_AGENT_PROVIDERS__<NAME>__TOKEN` | API/clone credential. |
| `hosts`            | `list[str]`                 | `[]`            | `REPO_AGENT_PROVIDERS__<NAME>__HOSTS` | Git hosts served by this provider, used to route repository URLs to it. |
| `namespaces`       | `list[str]`                 | `[]`            | `REPO_AGENT_PROVIDERS__<NAME>__NAMESPACES` | Organizations (GitHub) or groups (GitLab) whose repositories are discovered automatically. |
| `discovery`        | `DiscoveryMode \| None` (`none`, `namespaces`, `all`) | `None` (resolved to `namespaces` if `namespaces` is non-empty, else `none`) | `REPO_AGENT_PROVIDERS__<NAME>__DISCOVERY` | Repository discovery mode. `namespaces` requires a non-empty `namespaces` list; the generic `git` provider only supports `none`. |
| `exclude`          | `list[str]`                 | `[]`            | `REPO_AGENT_PROVIDERS__<NAME>__EXCLUDE` | Glob patterns (matched against name, full path, URL) applied only to repositories discovered through this provider, in addition to the global `repositories.exclude`. |
| `include_archived` | `bool`                      | `False`         | `REPO_AGENT_PROVIDERS__<NAME>__INCLUDE_ARCHIVED` | Include archived repositories in discovery. |
| `integration`      | `ProviderIntegration` (`native`, `mcp`, `both`) | `native` | `REPO_AGENT_PROVIDERS__<NAME>__INTEGRATION` | How provider capabilities reach the agent: built-in `provider_*` tools, the provider's MCP server, or both. |
| `mcp`              | `McpServerConfig \| None`    | `None`          | `REPO_AGENT_PROVIDERS__<NAME>__MCP__<KEY>` | Required when `integration` is `mcp`/`both`; see [MCP server](#mcp-server-providersnamemcp). |
| `timeout_seconds`  | `float`                     | `30.0`          | `REPO_AGENT_PROVIDERS__<NAME>__TIMEOUT_SECONDS` | HTTP timeout for provider API calls. |

### MCP server (`providers.<name>.mcp`)

`McpServerConfig`:

| Key             | Type                          | Default   | Description |
|-----------------|--------------------------------|-----------|--------------|
| `transport`     | `"stdio" \| "http"`            | `http`    | Transport used to reach the provider's MCP server. |
| `url`           | `str \| None`                  | `None`    | Required for `http` transport. |
| `command`       | `str \| None`                  | `None`    | Required for `stdio` transport (the command to launch). |
| `args`          | `list[str]`                    | `[]`      | Extra arguments for the `stdio` command. |
| `env`           | `dict[str, SecretStr]`         | `{}`      | Environment variables passed to the `stdio` process. |
| `headers`       | `dict[str, SecretStr]`         | `{}`      | Extra HTTP headers for the `http` transport. |
| `token_env`     | `str \| None`                  | `None`    | For `stdio` servers: environment variable that receives the provider token. |
| `forward_token` | `bool`                         | `True`    | For `http` servers: send the provider token as a bearer `Authorization` header. |
| `allowed_tools` | `list[str] \| None`            | `None`    | Restrict the MCP tools exposed to the agent (strongly recommended to keep it read-only). |

## Repositories (`repositories`)

`RepositoriesConfig`:

| Key      | Type                                    | Default | Description |
|----------|------------------------------------------|---------|--------------|
| `include`| `list[str \| RepositoryDefinition]`       | `[]`    | Explicit repositories, merged with anything discovered by providers (unless `mode = "explicit"`). A plain string is a URL; a table (`RepositoryDefinition`) can set `name`, `provider`, `full_path`, `default_branch`, `tags`. |
| `exclude`| `list[str]`                              | `[]`    | Glob patterns matched against repository name, full path and URL, applied globally (in addition to any per-provider `exclude`). |
| `mode`   | `RepositoriesMode` (`auto`, `explicit`)   | `auto`  | `auto` lets each provider discover per its own `discovery` setting; `explicit` disables all provider discovery regardless of provider settings, using only `include`. |

`RepositoryDefinition` (a table entry in `include`):

| Key              | Type            | Default   | Description |
|------------------|-----------------|-----------|--------------|
| `url`            | `str`           | *required*| Clone URL. |
| `name`           | `str \| None`   | `None`    | Defaults to the last URL path segment. |
| `provider`       | `str \| None`   | `None`    | Defaults to the provider whose `hosts` match the URL, else the generic `git` provider. |
| `full_path`      | `str \| None`   | `None`    | Namespace/path, e.g. `platform/service-a`. |
| `default_branch` | `str \| None`   | `None`    | |
| `tags`           | `list[str]`     | `[]`      | Used by group selectors. |

## Groups (`groups.<name>`)

`GroupDefinition` — membership is the union of explicit `repositories` and every repository matching
all given selectors (`patterns`, `tags`, `providers`, `namespaces`). A plain list under `[groups]` is
shorthand for `repositories`.

| Key            | Type          | Default | Description |
|----------------|---------------|---------|--------------|
| `description`  | `str \| None` | `None`  | |
| `repositories` | `list[str]`   | `[]`    | Explicit member names/paths/URLs. |
| `patterns`     | `list[str]`   | `[]`    | Glob patterns matched against name, full path and URL. |
| `tags`         | `list[str]`   | `[]`    | Match repositories carrying any of these tags. |
| `providers`    | `list[str]`   | `[]`    | Match repositories from these providers. |
| `namespaces`   | `list[str]`   | `[]`    | Glob patterns matched against the repository's namespace. |

## Agent (`agent`)

`AgentConfig`:

| Key                    | Type                                   | Default                     | Environment variable | Description |
|------------------------|------------------------------------------|-------------------------------|------------------------|--------------|
| `backend`              | `AgentBackend` (`pydantic-ai`, `claude-code`, `codex`) | `pydantic-ai`  | `REPO_AGENT_AGENT__BACKEND` | How the investigating agent is driven. The CLI backends skip the planner and run read-only. |
| `model`                | `str`                                   | `anthropic:claude-opus-5-5`  | `REPO_AGENT_AGENT__MODEL` | PydanticAI model string, or the model name known to `base_url`/the CLI. |
| `planner_model`        | `str \| None`                           | `None` (falls back to `model`)| `REPO_AGENT_AGENT__PLANNER_MODEL` | Optional cheaper model for the planning phase (`pydantic-ai` backend only). |
| `default_scope`        | `list[str]`                             | `[]`                          | `REPO_AGENT_AGENT__DEFAULT_SCOPE` | Group or repository names used when a question does not specify `--scope`. Empty means all. |
| `planning`             | `bool`                                  | `True`                        | `REPO_AGENT_AGENT__PLANNING` | Whether to run the planning phase (`pydantic-ai` backend only; overridable per-question with `--plan`/`--no-plan`). |
| `temperature`          | `float \| None`                         | `None`                        | `REPO_AGENT_AGENT__TEMPERATURE` | Model sampling temperature (`pydantic-ai` backend only). |
| `instructions`         | `str \| None`                           | `None`                        | `REPO_AGENT_AGENT__INSTRUCTIONS` | Extra organization-specific guidance appended to the agent instructions. |
| `base_url`             | `str \| None`                           | `None`                        | `REPO_AGENT_AGENT__BASE_URL` | Base URL of an OpenAI-compatible endpoint (Ollama, vLLM, LM Studio, llama.cpp server, LiteLLM) for the `pydantic-ai` backend. When set, `model`/`planner_model` are sent to this endpoint instead of the provider named by their prefix; a bare name or an `openai:` prefix are both accepted. |
| `api_key_env`          | `str \| None`                           | `None`                        | `REPO_AGENT_AGENT__API_KEY_ENV` | Name of the environment variable holding the API key for `base_url`. Many local servers need none; a dummy key is used when unset. |
| `cli_command`          | `str \| None`                           | `None` (`claude`/`codex`)     | `REPO_AGENT_AGENT__CLI_COMMAND` | Binary path override for the `claude-code`/`codex` backend. |
| `cli_args`             | `list[str]`                             | `[]`                          | `REPO_AGENT_AGENT__CLI_ARGS` | Extra command-line arguments appended when invoking the `claude-code`/`codex` CLI. |
| `cli_timeout_seconds`  | `float`                                 | `600.0`                       | `REPO_AGENT_AGENT__CLI_TIMEOUT_SECONDS` | Timeout for a single `claude-code`/`codex` CLI invocation, including its retry. |

## Sandbox (`sandbox`)

`SandboxConfig`:

| Key               | Type                          | Default                     | Environment variable | Description |
|-------------------|--------------------------------|-------------------------------|------------------------|--------------|
| `enabled`         | `bool`                        | `True`                        | `REPO_AGENT_SANDBOX__ENABLED` | When `false`, `run_in_sandbox` is removed from the agent entirely. |
| `backend`         | `SandboxBackend` (`docker`, `local`) | `docker`               | `REPO_AGENT_SANDBOX__BACKEND` | `local` runs commands as host subprocesses with rlimits only — not an isolation boundary; development only. |
| `image`           | `str`                         | `sherlockode-sandbox:latest`  | `REPO_AGENT_SANDBOX__IMAGE` | Docker image for sandbox containers. |
| `docker_binary`   | `str`                         | `docker`                      | `REPO_AGENT_SANDBOX__DOCKER_BINARY` | |
| `runtime`         | `str \| None`                 | `None`                        | `REPO_AGENT_SANDBOX__RUNTIME` | Alternative OCI runtime for stronger isolation, e.g. `runsc` (gVisor) or `sysbox-runc`. |
| `cpus`            | `float`                       | `1.0`                         | `REPO_AGENT_SANDBOX__CPUS` | |
| `memory`          | `str`                         | `1g`                          | `REPO_AGENT_SANDBOX__MEMORY` | |
| `pids_limit`      | `int`                         | `256`                         | `REPO_AGENT_SANDBOX__PIDS_LIMIT` | |
| `timeout_seconds` | `int`                         | `120`                         | `REPO_AGENT_SANDBOX__TIMEOUT_SECONDS` | |
| `network`         | `"none" \| "bridge"`          | `none`                        | `REPO_AGENT_SANDBOX__NETWORK` | |
| `user`            | `str`                         | `65534:65534`                 | `REPO_AGENT_SANDBOX__USER` | |
| `max_output_bytes`| `int`                         | `200_000`                     | `REPO_AGENT_SANDBOX__MAX_OUTPUT_BYTES` | |
| `passthrough_env` | `list[str]`                   | `[]`                          | `REPO_AGENT_SANDBOX__PASSTHROUGH_ENV` | Environment variable names forwarded into the sandbox container unchanged. |
| `host_workspace`  | `Path \| None`                | `None`                        | `REPO_AGENT_SANDBOX__HOST_WORKSPACE` | Host path of the workspace when the application itself runs in a container (Docker-out-of-Docker), used to translate bind-mount paths. |

## Limits (`limits`)

`LimitsConfig`:

| Key                     | Type          | Default   | Environment variable | Description |
|-------------------------|---------------|-----------|------------------------|--------------|
| `max_repositories`      | `int`         | `200`     | `REPO_AGENT_LIMITS__MAX_REPOSITORIES` | |
| `max_agent_requests`    | `int`         | `60`      | `REPO_AGENT_LIMITS__MAX_AGENT_REQUESTS` | Shared by planner and investigator. |
| `max_tool_calls`        | `int`         | `300`     | `REPO_AGENT_LIMITS__MAX_TOOL_CALLS` | Shared by planner and investigator. |
| `max_file_bytes`        | `int`         | `200_000` | `REPO_AGENT_LIMITS__MAX_FILE_BYTES` | |
| `max_search_results`    | `int`         | `200`     | `REPO_AGENT_LIMITS__MAX_SEARCH_RESULTS` | |
| `max_log_entries`       | `int`         | `2_000`   | `REPO_AGENT_LIMITS__MAX_LOG_ENTRIES` | |
| `git_timeout_seconds`   | `int`         | `600`     | `REPO_AGENT_LIMITS__GIT_TIMEOUT_SECONDS` | |
| `clone_depth`           | `int \| None` | `None`    | `REPO_AGENT_LIMITS__CLONE_DEPTH` | Shallow clone depth. `None` keeps full history, which history questions need. |

## Storage (`storage`)

`StorageConfig`:

| Key                     | Type          | Default | Environment variable | Description |
|-------------------------|---------------|---------|------------------------|--------------|
| `keep_investigations`   | `int \| None` | `None`  | `REPO_AGENT_STORAGE__KEEP_INVESTIGATIONS` | Number of investigation directories to retain. `None` keeps all of them. |
| `save_config_snapshot`  | `bool`        | `True`  | `REPO_AGENT_STORAGE__SAVE_CONFIG_SNAPSHOT` | Save a redacted configuration snapshot in each investigation's manifest. |
