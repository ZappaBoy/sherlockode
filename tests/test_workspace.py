from pathlib import Path

from sherlockcode.domain.repository import RepositoryRef
from sherlockcode.workspace import Workspace


def test_layout_and_investigation_sequence(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    workspace.initialize()

    first = workspace.new_investigation()
    second = workspace.new_investigation()

    assert first.id.endswith("-001") and second.id.endswith("-002")
    assert (workspace.artifacts / "reports").is_dir()
    assert [p.id for p in workspace.list_investigations()] == [first.id, second.id]


def test_prune_keeps_latest(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    workspace.initialize()
    ids = [workspace.new_investigation().id for _ in range(3)]

    workspace.prune_investigations(keep=1)

    assert [p.id for p in workspace.list_investigations()] == ids[-1:]


def test_checkout_paths_cannot_escape_workspace(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    repository = RepositoryRef(name="x", url="u", provider="../git", full_path="../../etc/passwd")

    path = workspace.checkout_path(repository)

    assert path.resolve().is_relative_to(workspace.repositories)
