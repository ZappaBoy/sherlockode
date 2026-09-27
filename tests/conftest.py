import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import BaseModel

from sherlockode.config.settings import Settings

PYPROJECT_A = '[project]\nname = "a"\nrequires-python = ">=3.11"\ndependencies = ["fastapi>=0.110"]\n'


class CommitSpec(BaseModel):
    files: dict[str, str]
    message: str
    author: str = "Alice <alice@example.com>"
    date: str = "2026-01-05T09:30:00+01:00"


def _git(repository: Path, *args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(["git", *args], cwd=repository, check=True, capture_output=True, env={**os.environ, **(env or {})})


def make_repository(root: Path, name: str, commits: list[CommitSpec]) -> Path:
    repository = root / name
    repository.mkdir(parents=True)
    _git(repository, "init", "--quiet", "--initial-branch=main")
    for commit in commits:
        for path, content in commit.files.items():
            file = repository / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content)
        _git(repository, "add", "--all")
        name_part, email = commit.author.rstrip(">").split(" <")
        env = {
            "GIT_AUTHOR_NAME": name_part,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name_part,
            "GIT_COMMITTER_EMAIL": email,
            "GIT_AUTHOR_DATE": commit.date,
            "GIT_COMMITTER_DATE": commit.date,
        }
        _git(repository, "commit", "--quiet", "-m", commit.message, env=env)
    return repository


@pytest.fixture
def remotes(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "remotes"
    service_a = make_repository(
        root,
        "service-a",
        [
            CommitSpec(
                files={"pyproject.toml": PYPROJECT_A},
                message="init",
            ),
            CommitSpec(
                files={"app/main.py": "import fastapi\n", "Dockerfile": "FROM python:3.11-slim\n"},
                message="add app",
                author="Bob <bob@example.com>",
                date="2026-02-01T21:15:00+01:00",
            ),
        ],
    )
    service_b = make_repository(
        root,
        "service-b",
        [
            CommitSpec(
                files={"pyproject.toml": '[project]\nname = "b"\nrequires-python = ">=3.12"\n', "b.py": "print(1)\n"},
                message="init",
            )
        ],
    )
    frontend = make_repository(
        root,
        "frontend",
        [
            CommitSpec(
                files={"package.json": '{"dependencies": {"react": "^19.0.0"}}', "index.ts": "export {}\n"},
                message="init",
            )
        ],
    )
    return {"service-a": service_a, "service-b": service_b, "frontend": frontend}


@pytest.fixture
def clean_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    for key in list(os.environ):
        if key.startswith("REPO_AGENT_"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture
def settings(tmp_path: Path, remotes: dict[str, Path], clean_environment: None) -> Settings:
    return Settings(
        workspace=tmp_path / "workspace",
        repositories={"include": [str(path) for path in remotes.values()]},
        groups={
            "python": ["service-a", "service-b"],
            "web": {"patterns": ["front*"], "description": "Web clients"},
        },
        sandbox={"backend": "local"},
    )
