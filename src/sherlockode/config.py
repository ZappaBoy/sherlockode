from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, Field

from .models import AgentToolConfig, ExecutionLimits, ProviderConfig, RepositoryGroup, RepositoryScope, SandboxConfig, WorkspaceConfig


class AppConfig(BaseModel):
    repositories: RepositoryScope = Field(default_factory=RepositoryScope)
    groups: dict[str, RepositoryGroup] = Field(default_factory=dict)
    providers: ProviderConfig = Field(default_factory=ProviderConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    execution_limits: ExecutionLimits = Field(default_factory=ExecutionLimits)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    agent_tools: AgentToolConfig = Field(default_factory=AgentToolConfig)
    default_investigation_scope: list[str] = Field(default_factory=list)
    log_level: str = "INFO"

    @classmethod
    def load(cls, config_path: Path | None = None, env: Mapping[str, str] | None = None) -> "AppConfig":
        env_data = dict(os.environ if env is None else env)
        base_data = cls._load_toml(config_path)
        merged = _deep_merge(base_data, cls._env_overrides(env_data))
        return cls.model_validate(merged)

    @staticmethod
    def _load_toml(config_path: Path | None) -> dict[str, Any]:
        if config_path is None:
            return {}
        with config_path.open("rb") as file:
            raw = tomllib.load(file)
        groups = _normalize_groups(raw.get("groups", {}))
        normalized = dict(raw)
        normalized["groups"] = groups
        return normalized

    @staticmethod
    def _env_overrides(env: Mapping[str, str]) -> dict[str, Any]:
        overrides: dict[str, Any] = {}
        mappings: dict[str, tuple[str, ...]] = {
            "REPO_AGENT_GITHUB_TOKEN": ("providers", "github_token"),
            "REPO_AGENT_GITLAB_TOKEN": ("providers", "gitlab_token"),
            "REPO_AGENT_WORKSPACE": ("workspace", "root"),
            "REPO_AGENT_SANDBOX_ENABLED": ("sandbox", "enabled"),
            "REPO_AGENT_LOG_LEVEL": ("log_level",),
            "REPO_AGENT_USE_MCP_SERVERS": ("agent_tools", "use_mcp_servers"),
        }
        for env_key, path in mappings.items():
            if env_key not in env:
                continue
            _set_nested_value(overrides, path, _coerce_env_value(env[env_key]))
        return overrides


def _normalize_groups(raw: Mapping[str, Any]) -> dict[str, dict[str, list[str]]]:
    groups: dict[str, dict[str, list[str]]] = {}
    for key, value in raw.items():
        if isinstance(value, list):
            groups[key] = {"repositories": [str(item) for item in value]}
        elif isinstance(value, Mapping):
            repositories = value.get("repositories", [])
            groups[key] = {"repositories": [str(item) for item in repositories]}
    return groups


def _coerce_env_value(value: str) -> Any:
    lowered = value.strip().lower()
    if lowered in {"true", "1", "yes", "on"}:
        return True
    if lowered in {"false", "0", "no", "off"}:
        return False
    return value


def _set_nested_value(target: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    current = target
    for key in path[:-1]:
        current = current.setdefault(key, {})
    current[path[-1]] = value


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
