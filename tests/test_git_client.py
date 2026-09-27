from pathlib import Path

import pytest

from sherlockcode.domain.activity import RefKind
from sherlockcode.git import CloneRequest, GitClient, GrepQuery, LogQuery


@pytest.fixture
async def checkout(remotes: dict[str, Path], tmp_path: Path) -> Path:
    destination = tmp_path / "checkout"
    await GitClient().clone(CloneRequest(url=str(remotes["service-a"]), destination=destination))
    return destination


async def test_log_returns_commits_newest_first(checkout: Path) -> None:
    commits = await GitClient().log(checkout, LogQuery())

    assert [commit.subject for commit in commits] == ["add app", "init"]
    assert commits[0].author.email == "bob@example.com"
    assert commits[0].authored_at.hour == 21


async def test_log_filters_by_path(checkout: Path) -> None:
    commits = await GitClient().log(checkout, LogQuery(paths=["pyproject.toml"]))

    assert [commit.subject for commit in commits] == ["init"]


async def test_contributors(checkout: Path) -> None:
    contributors = await GitClient().contributors(checkout)

    assert {c.person.name: c.contributions for c in contributors} == {"Alice": 1, "Bob": 1}


async def test_branches(checkout: Path) -> None:
    branches = await GitClient().refs(checkout, RefKind.BRANCH)

    assert [branch.name for branch in branches] == ["main"]


async def test_grep_and_files(checkout: Path) -> None:
    git = GitClient()

    matches = await git.grep(checkout, GrepQuery(pattern="requires-python"))
    files = await git.list_files(checkout, "*.py")

    assert [(m.path, m.line) for m in matches] == [("pyproject.toml", 3)]
    assert files == ["app/main.py"]


async def test_invalid_grep_pattern_raises(checkout: Path) -> None:
    with pytest.raises(ValueError):
        await GitClient().grep(checkout, GrepQuery(pattern="("))


async def test_show_file_at_revision(checkout: Path) -> None:
    content = await GitClient().show_file(checkout, "pyproject.toml", "HEAD~1")

    assert "requires-python" in content
