import os
from pathlib import Path
from typing import Any

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from sherlockcode.config.models import (
    AgentConfig,
    GroupDefinition,
    LimitsConfig,
    ProviderConfig,
    ProviderKind,
    RepositoriesConfig,
    SandboxConfig,
    StorageConfig,
)

ENV_PREFIX = "REPO_AGENT_"
CONFIG_PATH_ENV = f"{ENV_PREFIX}CONFIG"
DEFAULT_CONFIG_PATH = Path("sherlockcode.toml")
GENERIC_PROVIDER = "git"


# Application settings.
#
# Precedence, highest first: environment variables, `.env`, TOML file, defaults.
# Nested values use `__` as delimiter, e.g. `REPO_AGENT_SANDBOX__ENABLED=false`.
# Provider tokens also accept the shorthand `REPO_AGENT_<PROVIDER>_TOKEN`.
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        toml_file=DEFAULT_CONFIG_PATH,
    )

    workspace: Path = Field(default=Path("workspace"), description="Directory holding clones and investigations.")
    log_level: str = Field(default="INFO", description="Python logging level name, e.g. DEBUG, INFO, WARNING.")
    providers: dict[str, ProviderConfig] = Field(
        default_factory=dict, description="Repository hosting providers, keyed by provider name."
    )
    repositories: RepositoriesConfig = Field(
        default_factory=RepositoriesConfig, description="Explicit repository selection and global exclusions."
    )
    groups: dict[str, GroupDefinition] = Field(
        default_factory=dict,
        description=(
            "Logical groups of repositories, independent of the hosting provider, keyed by group name. "
            "Membership is the union of explicit repositories and every repository matching all given selectors."
        ),
    )
    agent: AgentConfig = Field(default_factory=AgentConfig, description="Investigating agent backend and model.")
    sandbox: SandboxConfig = Field(
        default_factory=SandboxConfig, description="Disposable execution sandbox for the analysis tools."
    )
    limits: LimitsConfig = Field(default_factory=LimitsConfig, description="Resource and pagination limits.")
    storage: StorageConfig = Field(
        default_factory=StorageConfig, description="Investigation storage retention and snapshot behavior."
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )

    @model_validator(mode="after")
    def _finalize_providers(self) -> "Settings":
        self.providers.setdefault(GENERIC_PROVIDER, ProviderConfig(kind=ProviderKind.GIT))
        for name, provider in self.providers.items():
            if provider.token is None:
                provider.token = _token_from_environment(name)
        return self

    def redacted(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _token_from_environment(provider_name: str) -> SecretStr | None:
    variable = f"{ENV_PREFIX}{provider_name.upper().replace('-', '_')}_TOKEN"
    value = os.environ.get(variable)
    return SecretStr(value) if value else None


def load_settings(config_path: Path | None = None) -> Settings:
    path = config_path or Path(os.environ.get(CONFIG_PATH_ENV, DEFAULT_CONFIG_PATH))
    if config_path is not None and not path.is_file():
        raise FileNotFoundError(f"configuration file not found: {path}")
    bound: type[Settings] = type(
        "BoundSettings",
        (Settings,),
        {"model_config": SettingsConfigDict(**{**Settings.model_config, "toml_file": path})},
    )
    return bound()
