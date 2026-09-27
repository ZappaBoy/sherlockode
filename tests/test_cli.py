from pathlib import Path

import pytest
from typer.testing import CliRunner

from sherlockcode.cli import app


@pytest.fixture
def config_file(tmp_path: Path, remotes: dict[str, Path], clean_environment: None) -> Path:
    path = tmp_path / "sherlockcode.toml"
    includes = ", ".join(f'"{remote}"' for remote in remotes.values())
    path.write_text(
        f'workspace = "{tmp_path / "ws"}"\n[repositories]\ninclude = [{includes}]\n[groups]\npy = ["service-a"]\n'
    )
    return path


def test_repos_and_sync(config_file: Path) -> None:
    runner = CliRunner()

    synced = runner.invoke(app, ["-c", str(config_file), "sync", "--scope", "py"])
    listed = runner.invoke(app, ["-c", str(config_file), "repos"])

    assert synced.exit_code == 0 and "service-a" in synced.output
    assert listed.exit_code == 0
    assert {"service-a", "service-b", "frontend"} <= set(listed.output.split())


def test_unknown_scope_exits_with_usage_error(config_file: Path) -> None:
    result = CliRunner().invoke(app, ["-c", str(config_file), "repos", "--scope", "missing"])

    assert result.exit_code == 2 and "missing" in result.output


def test_config_is_redacted(config_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPO_AGENT_GIT_TOKEN", "super-secret")

    result = CliRunner().invoke(app, ["-c", str(config_file), "config"])

    assert result.exit_code == 0 and "super-secret" not in result.output
