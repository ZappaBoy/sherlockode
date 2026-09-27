from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr


class ProviderKind(str, Enum):
    GIT = "git"
    GITHUB = "github"
    GITLAB = "gitlab"


class RepositoryDefinition(BaseModel):
    name: str
    url: str
    provider: ProviderKind = ProviderKind.GIT
    tags: list[str] = Field(default_factory=list)


class RepositoryScope(BaseModel):
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)


class RepositoryGroup(BaseModel):
    repositories: list[str] = Field(default_factory=list)


class ExecutionLimits(BaseModel):
    cpu_cores: int = 2
    memory_mb: int = 1024
    timeout_seconds: int = 120
    max_processes: int = 32


class SandboxConfig(BaseModel):
    enabled: bool = True
    network_enabled: bool = False
    non_root: bool = True
    restricted_env_vars: list[str] = Field(default_factory=list)


class WorkspaceConfig(BaseModel):
    root: Path = Path("workspace")
    repositories_dir: str = "repositories"
    investigations_dir: str = "investigations"
    artifacts_dir: str = "artifacts"
    cache_dir: str = "cache"


class AgentToolConfig(BaseModel):
    use_mcp_servers: bool = True
    allow_custom_tools: bool = True


class ProviderConfig(BaseModel):
    github_token: SecretStr | None = None
    gitlab_token: SecretStr | None = None
    github_mcp_enabled: bool = True
    gitlab_mcp_enabled: bool = True
