from pathlib import Path

import pytest
from pydantic import ValidationError

from sherlockcode.config import ProviderIntegration, load_settings
from sherlockcode.config.models import DiscoveryMode, ProviderConfig, RepositoriesConfig, RepositoriesMode

CONFIG = """
workspace = "from-toml"
log_level = "DEBUG"

[providers.github]
kind = "github"
namespaces = ["example"]

[repositories]
include = [
    "git@gitlab.example.com:platform/service-a.git",
    { url = "https://github.com/example/service-b.git", tags = ["python"] },
]
exclude = ["*-archive"]

[groups]
legacy = ["project-x", "project-y"]

[groups.python]
repositories = ["service-a"]
tags = ["python"]

[sandbox]
memory = "2g"
"""


@pytest.fixture
def config_file(tmp_path: Path, clean_environment: None) -> Path:
    path = tmp_path / "sherlockcode.toml"
    path.write_text(CONFIG)
    return path


def test_toml_values_are_loaded(config_file: Path) -> None:
    settings = load_settings(config_file)

    assert settings.workspace == Path("from-toml")
    assert settings.providers["github"].namespaces == ["example"]
    assert settings.groups["legacy"].repositories == ["project-x", "project-y"]
    assert settings.groups["python"].tags == ["python"]
    assert [d.url for d in settings.repositories.definitions()][1] == "https://github.com/example/service-b.git"
    assert settings.sandbox.memory == "2g"


def test_generic_git_provider_is_always_present(config_file: Path) -> None:
    assert load_settings(config_file).providers["git"].kind == "git"


def test_environment_overrides_toml(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPO_AGENT_WORKSPACE", "/data/workspace")
    monkeypatch.setenv("REPO_AGENT_SANDBOX__ENABLED", "false")
    monkeypatch.setenv("REPO_AGENT_SANDBOX__MEMORY", "512m")

    settings = load_settings(config_file)

    assert settings.workspace == Path("/data/workspace")
    assert settings.sandbox.enabled is False
    assert settings.sandbox.memory == "512m"


def test_dotenv_is_below_environment(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    Path(".env").write_text("REPO_AGENT_LOG_LEVEL=WARNING\nREPO_AGENT_WORKSPACE=/from-dotenv\n")
    monkeypatch.setenv("REPO_AGENT_WORKSPACE", "/from-env")

    settings = load_settings(config_file)

    assert settings.log_level == "WARNING"
    assert settings.workspace == Path("/from-env")


def test_provider_token_shorthand(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPO_AGENT_GITHUB_TOKEN", "secret")

    settings = load_settings(config_file)

    token = settings.providers["github"].token
    assert token is not None and token.get_secret_value() == "secret"
    assert "secret" not in str(settings.redacted())


def test_missing_explicit_config_fails(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "missing.toml")


def test_mcp_integration_requires_server() -> None:
    with pytest.raises(ValidationError):
        ProviderConfig(kind="github", integration=ProviderIntegration.MCP)


def test_http_mcp_server_requires_url() -> None:
    with pytest.raises(ValidationError):
        ProviderConfig(kind="github", integration=ProviderIntegration.MCP, mcp={"transport": "http"})


def test_discovery_defaults_to_namespaces_when_namespaces_given() -> None:
    assert ProviderConfig(kind="github", namespaces=["o"]).discovery == DiscoveryMode.NAMESPACES


def test_discovery_defaults_to_none_without_namespaces() -> None:
    assert ProviderConfig(kind="github").discovery == DiscoveryMode.NONE


def test_discovery_mode_all_does_not_require_namespaces() -> None:
    assert ProviderConfig(kind="github", discovery=DiscoveryMode.ALL).discovery == DiscoveryMode.ALL


def test_discovery_namespaces_mode_requires_namespaces() -> None:
    with pytest.raises(ValidationError):
        ProviderConfig(kind="github", discovery=DiscoveryMode.NAMESPACES)


def test_generic_git_provider_cannot_enable_discovery() -> None:
    with pytest.raises(ValidationError):
        ProviderConfig(kind="git", discovery=DiscoveryMode.ALL)


def test_repositories_explicit_mode_is_a_valid_value() -> None:
    config = RepositoriesConfig.model_validate({"mode": "explicit"})
    assert config.mode == RepositoriesMode.EXPLICIT
