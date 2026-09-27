from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderKind(StrEnum):
    GIT = "git"
    GITHUB = "github"
    GITLAB = "gitlab"


# How provider-specific capabilities are exposed to the agent.
class ProviderIntegration(StrEnum):
    NATIVE = "native"
    MCP = "mcp"
    BOTH = "both"


class McpServerConfig(_Section):
    transport: Literal["stdio", "http"] = Field(
        default="http", description="How the MCP server is reached: a local subprocess or an HTTP endpoint."
    )
    url: str | None = Field(default=None, description="MCP server URL, required when 'transport' is 'http'.")
    command: str | None = Field(
        default=None, description="Subprocess command to launch the MCP server, required when 'transport' is 'stdio'."
    )
    args: list[str] = Field(default_factory=list, description="Extra arguments passed to 'command'.")
    env: dict[str, SecretStr] = Field(
        default_factory=dict, description="Extra environment variables passed to the 'stdio' subprocess."
    )
    headers: dict[str, SecretStr] = Field(
        default_factory=dict, description="Extra HTTP headers sent with every request to an 'http' server."
    )
    token_env: str | None = Field(
        default=None, description="For stdio servers: the environment variable that receives the provider token."
    )
    forward_token: bool = Field(
        default=True, description="For HTTP servers: send the provider token as a bearer Authorization header."
    )
    allowed_tools: list[str] | None = Field(
        default=None,
        description="Restrict the MCP tools exposed to the agent. Read-only tools are strongly recommended.",
    )

    @model_validator(mode="after")
    def _check_transport(self) -> "McpServerConfig":
        if self.transport == "http" and not self.url:
            raise ValueError("an http MCP server requires 'url'")
        if self.transport == "stdio" and not self.command:
            raise ValueError("a stdio MCP server requires 'command'")
        return self


# How a provider discovers repositories, independent of explicit `[repositories] include`.
class DiscoveryMode(StrEnum):
    NONE = "none"
    NAMESPACES = "namespaces"
    ALL = "all"


class ProviderConfig(_Section):
    kind: str = Field(
        description="Provider implementation name registered in the provider registry, e.g. github, gitlab, git."
    )
    base_url: str | None = Field(default=None, description="Base URL of the provider's API, for self-hosted instances.")
    token: SecretStr | None = Field(default=None, description="API token used to authenticate against the provider.")
    hosts: list[str] = Field(
        default_factory=list, description="Git hosts served by this provider, used to route repository URLs to it."
    )
    namespaces: list[str] = Field(
        default_factory=list,
        description="Organizations (GitHub) or groups (GitLab) whose repositories are discovered automatically.",
    )
    discovery: DiscoveryMode | None = Field(
        default=None,
        description=(
            "Repository discovery mode: 'none' discovers nothing, 'namespaces' discovers only repositories "
            "under 'namespaces' (including subgroups for GitLab), 'all' discovers every repository the "
            "provider token can access. Defaults to 'namespaces' when 'namespaces' is non-empty, otherwise "
            "'none'. The generic 'git' provider only supports 'none'."
        ),
    )
    exclude: list[str] = Field(
        default_factory=list,
        description=(
            "Glob patterns matched against repository name, full path and URL, applied only to repositories "
            "discovered through this provider (in addition to the global [repositories] exclude)."
        ),
    )
    include_archived: bool = Field(default=False, description="Include archived repositories in discovery.")
    integration: ProviderIntegration = Field(
        default=ProviderIntegration.NATIVE,
        description="How provider-specific capabilities are exposed to the agent: 'native' Python tools, "
        "'mcp' tools from the configured MCP server, or 'both'.",
    )
    mcp: McpServerConfig | None = Field(
        default=None, description="MCP server configuration, required when 'integration' is 'mcp' or 'both'."
    )
    timeout_seconds: float = Field(default=30.0, description="Timeout for requests to the provider's API.")

    @model_validator(mode="after")
    def _check_mcp(self) -> "ProviderConfig":
        if self.integration != ProviderIntegration.NATIVE and self.mcp is None:
            raise ValueError(f"integration '{self.integration}' requires an [mcp] section")
        return self

    @model_validator(mode="after")
    def _resolve_discovery(self) -> "ProviderConfig":
        if self.discovery is None:
            self.discovery = DiscoveryMode.NAMESPACES if self.namespaces else DiscoveryMode.NONE
        if self.discovery == DiscoveryMode.NAMESPACES and not self.namespaces:
            raise ValueError("discovery mode 'namespaces' requires a non-empty 'namespaces' list")
        if self.kind == ProviderKind.GIT and self.discovery != DiscoveryMode.NONE:
            raise ValueError("the generic 'git' provider only supports discovery mode 'none'")
        return self


class RepositoryDefinition(_Section):
    url: str = Field(description="Repository clone/API URL.")
    name: str | None = Field(default=None, description="Display name; derived from the URL when unset.")
    provider: str | None = Field(
        default=None, description="Provider name to route this repository to; inferred from the URL when unset."
    )
    full_path: str | None = Field(
        default=None, description="Namespaced path (e.g. 'org/name') used for matching and display."
    )
    default_branch: str | None = Field(default=None, description="Branch checked out when none is specified.")
    tags: list[str] = Field(default_factory=list, description="Free-form tags usable in group selectors.")


# Convenience switch for the overall repository selection strategy.
class RepositoriesMode(StrEnum):
    AUTO = "auto"
    EXPLICIT = "explicit"


class RepositoriesConfig(_Section):
    include: list[str | RepositoryDefinition] = Field(
        default_factory=list, description="Repository URLs or full definitions to include explicitly."
    )
    exclude: list[str] = Field(
        default_factory=list, description="Glob patterns matched against repository name, full path and URL."
    )
    mode: RepositoriesMode = Field(
        default=RepositoriesMode.AUTO,
        description=(
            "'auto' lets each provider discover repositories per its own 'discovery' setting; 'explicit' "
            "disables all provider discovery regardless of provider settings, using only 'include'."
        ),
    )

    def definitions(self) -> list[RepositoryDefinition]:
        return [RepositoryDefinition(url=entry) if isinstance(entry, str) else entry for entry in self.include]


class GroupDefinition(_Section):
    description: str | None = Field(default=None, description="Human-readable description of the group.")
    repositories: list[str] = Field(
        default_factory=list, description="Explicit repository or full-path names included in the group."
    )
    patterns: list[str] = Field(
        default_factory=list, description="Glob patterns matched against repository name, full path or URL."
    )
    tags: list[str] = Field(default_factory=list, description="Include repositories carrying any of these tags.")
    providers: list[str] = Field(
        default_factory=list, description="Include repositories served by any of these providers."
    )
    namespaces: list[str] = Field(
        default_factory=list, description="Include repositories whose namespace matches any of these globs."
    )

    @model_validator(mode="before")
    @classmethod
    def _from_list(cls, value: Any) -> Any:
        return {"repositories": value} if isinstance(value, list) else value

    @property
    def has_selectors(self) -> bool:
        return bool(self.patterns or self.tags or self.providers or self.namespaces)


class SandboxBackend(StrEnum):
    DOCKER = "docker"
    # Runs commands as host subprocesses with rlimits only. Not an isolation boundary.
    LOCAL = "local"


class SandboxConfig(_Section):
    enabled: bool = Field(default=True, description="Whether the sandbox tool is offered to the agent at all.")
    backend: SandboxBackend = Field(
        default=SandboxBackend.DOCKER, description="Execution backend for sandboxed scripts."
    )
    image: str = Field(default="sherlockcode-sandbox:latest", description="Docker image used by the 'docker' backend.")
    docker_binary: str = Field(default="docker", description="Docker (or compatible) CLI binary to invoke.")
    runtime: str | None = Field(
        default=None,
        description="Alternative OCI runtime for stronger isolation, e.g. `runsc` (gVisor) or `sysbox-runc`.",
    )
    cpus: float = Field(default=1.0, description="CPU limit for a sandbox run.")
    memory: str = Field(default="1g", description="Memory limit for a sandbox run, in Docker's size notation.")
    pids_limit: int = Field(default=256, description="Maximum number of processes a sandbox run may spawn.")
    timeout_seconds: int = Field(default=120, description="Wall-clock timeout for a single sandbox run.")
    network: Literal["none", "bridge"] = Field(default="none", description="Network mode for sandbox containers.")
    user: str = Field(default="65534:65534", description="uid:gid the sandboxed process runs as.")
    max_output_bytes: int = Field(default=200_000, description="Maximum captured stdout/stderr size per run.")
    passthrough_env: list[str] = Field(
        default_factory=list, description="Host environment variable names forwarded into the sandbox."
    )
    host_workspace: Path | None = Field(
        default=None,
        description="Host path of the workspace when the application itself runs in a container "
        "(Docker-out-of-Docker).",
    )


class LimitsConfig(_Section):
    max_repositories: int = Field(default=200, description="Maximum number of repositories in a single scope.")
    max_agent_requests: int = Field(default=60, description="Maximum number of model requests per investigation.")
    max_tool_calls: int = Field(default=300, description="Maximum number of tool calls per investigation.")
    max_file_bytes: int = Field(default=200_000, description="Maximum size of a file the agent may read.")
    max_search_results: int = Field(default=200, description="Maximum matches returned per repository search.")
    max_log_entries: int = Field(default=2_000, description="Maximum commits returned per git log query.")
    git_timeout_seconds: int = Field(default=600, description="Timeout for a single git subprocess invocation.")
    clone_depth: int | None = Field(
        default=None, description="Shallow clone depth. None keeps the full history, which history questions need."
    )


# How the investigating agent is driven.
class AgentBackend(StrEnum):
    PYDANTIC_AI = "pydantic-ai"
    CLAUDE_CODE = "claude-code"
    CODEX = "codex"


class AgentConfig(_Section):
    backend: AgentBackend = Field(
        default=AgentBackend.PYDANTIC_AI,
        description=(
            "How the investigating agent is driven: 'pydantic-ai' (in-process, any PydanticAI model string), "
            "'claude-code' or 'codex' (drive the official CLI non-interactively, read-only, planner is skipped)."
        ),
    )
    model: str = Field(
        default="anthropic:claude-opus-5-5", description="PydanticAI model string for the investigating agent."
    )
    planner_model: str | None = Field(
        default=None, description="Model string for the planning phase; defaults to 'model' when unset."
    )
    default_scope: list[str] = Field(
        default_factory=list,
        description="Group or repository names used when a question does not specify a scope. Empty means all.",
    )
    planning: bool = Field(default=True, description="Whether to run a separate planning phase before investigating.")
    temperature: float | None = Field(default=None, description="Sampling temperature passed to the model.")
    instructions: str | None = Field(
        default=None, description="Extra organization-specific guidance appended to the agent instructions."
    )
    base_url: str | None = Field(
        default=None,
        description=(
            "Base URL of an OpenAI-compatible endpoint (Ollama, vLLM, LM Studio, llama.cpp server, LiteLLM) for "
            "the 'pydantic-ai' backend. When set, 'model'/'planner_model' are sent to this endpoint instead of "
            "the provider named by their prefix; a bare name or an 'openai:' prefix are both accepted."
        ),
    )
    api_key_env: str | None = Field(
        default=None,
        description=(
            "Name of the environment variable holding the API key for 'base_url'. Many local servers need none; "
            "a dummy key is used when unset."
        ),
    )
    cli_command: str | None = Field(
        default=None,
        description="Binary path override for the 'claude-code'/'codex' backend, defaults to 'claude'/'codex'.",
    )
    cli_args: list[str] = Field(
        default_factory=list,
        description="Extra command-line arguments appended when invoking the 'claude-code'/'codex' CLI.",
    )
    cli_timeout_seconds: float = Field(
        default=600.0,
        description="Timeout for a single 'claude-code'/'codex' CLI invocation, including its retry.",
    )


class StorageConfig(_Section):
    keep_investigations: int | None = Field(
        default=None, description="Number of investigation directories to retain. None keeps all of them."
    )
    save_config_snapshot: bool = Field(
        default=True, description="Save a redacted snapshot of the effective configuration with each investigation."
    )
