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


class ProviderIntegration(StrEnum):
    """How provider-specific capabilities are exposed to the agent."""

    NATIVE = "native"
    MCP = "mcp"
    BOTH = "both"


class McpServerConfig(_Section):
    transport: Literal["stdio", "http"] = "http"
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, SecretStr] = Field(default_factory=dict)
    headers: dict[str, SecretStr] = Field(default_factory=dict)
    token_env: str | None = None
    """For stdio servers: the environment variable that receives the provider token."""
    forward_token: bool = True
    """For HTTP servers: send the provider token as a bearer Authorization header."""
    allowed_tools: list[str] | None = None
    """Restrict the MCP tools exposed to the agent. Read-only tools are strongly recommended."""

    @model_validator(mode="after")
    def _check_transport(self) -> "McpServerConfig":
        if self.transport == "http" and not self.url:
            raise ValueError("an http MCP server requires 'url'")
        if self.transport == "stdio" and not self.command:
            raise ValueError("a stdio MCP server requires 'command'")
        return self


class ProviderConfig(_Section):
    kind: str
    """Provider implementation name registered in the provider registry, e.g. github, gitlab, git."""
    base_url: str | None = None
    token: SecretStr | None = None
    hosts: list[str] = Field(default_factory=list)
    """Git hosts served by this provider, used to route repository URLs to it."""
    namespaces: list[str] = Field(default_factory=list)
    """Organizations (GitHub) or groups (GitLab) whose repositories are discovered automatically."""
    include_archived: bool = False
    integration: ProviderIntegration = ProviderIntegration.NATIVE
    mcp: McpServerConfig | None = None
    timeout_seconds: float = 30.0

    @model_validator(mode="after")
    def _check_mcp(self) -> "ProviderConfig":
        if self.integration != ProviderIntegration.NATIVE and self.mcp is None:
            raise ValueError(f"integration '{self.integration}' requires an [mcp] section")
        return self


class RepositoryDefinition(_Section):
    url: str
    name: str | None = None
    provider: str | None = None
    full_path: str | None = None
    default_branch: str | None = None
    tags: list[str] = Field(default_factory=list)


class RepositoriesConfig(_Section):
    include: list[str | RepositoryDefinition] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    """Glob patterns matched against repository name, full path and URL."""

    def definitions(self) -> list[RepositoryDefinition]:
        return [RepositoryDefinition(url=entry) if isinstance(entry, str) else entry for entry in self.include]


class GroupDefinition(_Section):
    """A logical group of repositories, independent of the hosting provider.

    Membership is the union of explicit repositories and every repository matching all given selectors.
    """

    description: str | None = None
    repositories: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    providers: list[str] = Field(default_factory=list)
    namespaces: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _from_list(cls, value: Any) -> Any:
        return {"repositories": value} if isinstance(value, list) else value

    @property
    def has_selectors(self) -> bool:
        return bool(self.patterns or self.tags or self.providers or self.namespaces)


class SandboxBackend(StrEnum):
    DOCKER = "docker"
    LOCAL = "local"
    """Runs commands as host subprocesses with rlimits only. Not an isolation boundary."""


class SandboxConfig(_Section):
    enabled: bool = True
    backend: SandboxBackend = SandboxBackend.DOCKER
    image: str = "sherlockode-sandbox:latest"
    docker_binary: str = "docker"
    runtime: str | None = None
    """Alternative OCI runtime for stronger isolation, e.g. `runsc` (gVisor) or `sysbox-runc`."""
    cpus: float = 1.0
    memory: str = "1g"
    pids_limit: int = 256
    timeout_seconds: int = 120
    network: Literal["none", "bridge"] = "none"
    user: str = "65534:65534"
    max_output_bytes: int = 200_000
    passthrough_env: list[str] = Field(default_factory=list)
    host_workspace: Path | None = None
    """Host path of the workspace when the application itself runs in a container (Docker-out-of-Docker)."""


class LimitsConfig(_Section):
    max_repositories: int = 200
    max_agent_requests: int = 60
    max_tool_calls: int = 300
    max_file_bytes: int = 200_000
    max_search_results: int = 200
    max_log_entries: int = 2_000
    git_timeout_seconds: int = 600
    clone_depth: int | None = None
    """Shallow clone depth. None keeps the full history, which history questions need."""


class AgentConfig(_Section):
    model: str = "anthropic:claude-opus-5-5"
    planner_model: str | None = None
    default_scope: list[str] = Field(default_factory=list)
    """Group or repository names used when a question does not specify a scope. Empty means all."""
    planning: bool = True
    temperature: float | None = None
    instructions: str | None = None
    """Extra organization-specific guidance appended to the agent instructions."""


class StorageConfig(_Section):
    keep_investigations: int | None = None
    """Number of investigation directories to retain. None keeps all of them."""
    save_config_snapshot: bool = True
