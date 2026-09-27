import json
import re
import tomllib
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from sherlockcode.analysis.base import AnalysisTarget, Analyzer, AnalyzerReport, FileFinding, line_of


class Dependency(BaseModel):
    ecosystem: str
    name: str
    specifier: str
    path: str
    line: int | None = None


_REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*(.*)$")
_GO_REQUIRE = re.compile(r"^\s*(?:require\s+)?([\w.\-/]+\.[\w.\-/]+)\s+(v[\w.\-+]+)")

Parser = Callable[[str, str], list[Dependency]]


def _pip_requirement(raw: str, path: str, text: str) -> Dependency | None:
    match = _REQUIREMENT.match(raw.split("#", 1)[0].split(";", 1)[0])
    if not match:
        return None
    return Dependency(
        ecosystem="python",
        name=match.group(1).lower(),
        specifier=match.group(3).strip(),
        path=path,
        line=line_of(text, raw),
    )


def _parse_requirements(text: str, path: str) -> list[Dependency]:
    lines = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith(("#", "-"))]
    return [dependency for line in lines if (dependency := _pip_requirement(line, path, text))]


def _parse_pyproject(text: str, path: str) -> list[Dependency]:
    data = tomllib.loads(text)
    project = data.get("project", {})
    requirements = list(project.get("dependencies", []))
    requirements += [r for group in project.get("optional-dependencies", {}).values() for r in group]
    requirements += [r for group in data.get("dependency-groups", {}).values() for r in group if isinstance(r, str)]
    found = [dependency for raw in requirements if (dependency := _pip_requirement(raw, path, text))]
    poetry = data.get("tool", {}).get("poetry", {})
    poetry_tables = [poetry.get("dependencies", {})]
    poetry_tables += [group.get("dependencies", {}) for group in poetry.get("group", {}).values()]
    found += [
        Dependency(
            ecosystem="python", name=name.lower(), specifier=_poetry_spec(spec), path=path, line=line_of(text, name)
        )
        for table in poetry_tables
        for name, spec in table.items()
        if name.lower() != "python"
    ]
    return found


def _poetry_spec(spec: Any) -> str:
    return str(spec.get("version", "")) if isinstance(spec, dict) else str(spec)


def _parse_package_json(text: str, path: str) -> list[Dependency]:
    data = json.loads(text)
    sections = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")
    return [
        Dependency(ecosystem="npm", name=name, specifier=str(spec), path=path, line=line_of(text, f'"{name}"'))
        for section in sections
        for name, spec in data.get(section, {}).items()
    ]


def _parse_go_mod(text: str, path: str) -> list[Dependency]:
    return [
        Dependency(ecosystem="go", name=match.group(1), specifier=match.group(2), path=path, line=number)
        for number, line in enumerate(text.splitlines(), start=1)
        if not line.lstrip().startswith("module") and (match := _GO_REQUIRE.match(line))
    ]


_PARSERS: dict[tuple[str, ...], Parser] = {
    ("requirements*.txt", "requirements/*.txt"): _parse_requirements,
    ("pyproject.toml",): _parse_pyproject,
    ("package.json",): _parse_package_json,
    ("go.mod",): _parse_go_mod,
}


class DependencyAnalyzer(Analyzer):
    name = "dependencies"
    description = (
        "Lists declared dependencies from requirements*.txt, pyproject.toml (PEP 621, dependency groups, Poetry), "
        "package.json and go.mod, with file and line."
    )

    def analyze(self, target: AnalysisTarget) -> AnalyzerReport:
        dependencies: list[Dependency] = []
        errors: list[str] = []
        for patterns, parse in _PARSERS.items():
            for path in target.matching(*patterns):
                if "node_modules/" in path or (text := target.read(path)) is None:
                    continue
                try:
                    dependencies += parse(text, path)
                except (ValueError, tomllib.TOMLDecodeError) as error:
                    errors.append(f"{path}: {error}")
        evidence = [
            target.file_evidence(
                FileFinding(
                    statement=f"declares {d.ecosystem} dependency {d.name} {d.specifier}".rstrip(),
                    path=d.path,
                    line=d.line,
                )
            )
            for d in dependencies
        ]
        summary = {"dependencies": [d.model_dump() for d in dependencies], "parse_errors": errors}
        return self.report(target, summary, evidence)
