from pathlib import Path

from sherlockcode.analysis import AnalysisTarget, default_analyzers
from sherlockcode.domain.repository import RepositoryRef


def _target(tmp_path: Path, files: dict[str, str]) -> AnalysisTarget:
    for path, content in files.items():
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content)
    return AnalysisTarget(
        repository=RepositoryRef(name="repo", url="u", provider="git"),
        checkout=tmp_path,
        files=list(files),
        commit="abc123",
    )


def test_python_versions_from_multiple_sources(tmp_path: Path) -> None:
    target = _target(
        tmp_path,
        {
            "pyproject.toml": '[project]\nrequires-python = ">=3.10,<4"\n',
            "Dockerfile": "FROM docker.io/library/python:3.12-slim AS base\n",
            ".github/workflows/ci.yml": "  python-version: ['3.10', '3.11']\n",
            "tox.ini": "[tox]\nenvlist = py39, py310\n",
        },
    )

    report = default_analyzers().get("python_versions").analyze(target)

    assert report.summary["declared_versions"] == ["3.9", "3.10", "3.11", "3.12"]
    assert report.summary["lowest_declared_version"] == "3.9"
    sources = {(e.source.path, e.source.line) for e in report.evidence}
    assert ("pyproject.toml", 2) in sources and ("Dockerfile", 1) in sources


def test_dependencies(tmp_path: Path) -> None:
    target = _target(
        tmp_path,
        {
            "requirements.txt": "# pinned\nDjango==4.2 ; python_version >= '3.10'\n-r base.txt\nrequests[socks]>=2\n",
            "package.json": '{"dependencies": {"react": "^19.0.0"}, "devDependencies": {"vite": "6"}}',
            "go.mod": "module x\n\nrequire (\n\tgithub.com/pkg/errors v0.9.1\n)\n",
        },
    )

    report = default_analyzers().get("dependencies").analyze(target)

    found = {(d["ecosystem"], d["name"], d["specifier"], d["line"]) for d in report.summary["dependencies"]}
    assert found == {
        ("python", "django", "==4.2", 2),
        ("python", "requests", ">=2", 4),
        ("npm", "react", "^19.0.0", 1),
        ("npm", "vite", "6", 1),
        ("go", "github.com/pkg/errors", "v0.9.1", 4),
    }


def test_languages(tmp_path: Path) -> None:
    target = _target(tmp_path, {"a.py": "", "b.py": "", "c.ts": "", "README": ""})

    report = default_analyzers().get("languages").analyze(target)

    assert report.summary == {"primary_language": "Python", "files_per_language": {"Python": 2, "TypeScript": 1}}


def test_oversized_files_are_skipped(tmp_path: Path) -> None:
    target = _target(tmp_path, {"pyproject.toml": 'requires-python = ">=3.8"\n' + "#" * 1000})

    report = default_analyzers().get("python_versions").analyze(target.model_copy(update={"max_file_bytes": 10}))

    assert report.summary["declared_versions"] == []
