import re

from pydantic import BaseModel

from sherlockcode.analysis.base import AnalysisTarget, Analyzer, AnalyzerReport, FileFinding


class VersionRule(BaseModel):
    source: str
    patterns: tuple[str, ...]
    regex: re.Pattern[str]


_RULES = [
    VersionRule(
        source="requires-python",
        patterns=("pyproject.toml",),
        regex=re.compile(r"^\s*requires-python\s*=\s*[\"']([^\"']+)"),
    ),
    VersionRule(
        source="poetry python", patterns=("pyproject.toml",), regex=re.compile(r"^\s*python\s*=\s*[\"']([^\"']+)")
    ),
    VersionRule(
        source="python_requires",
        patterns=("setup.py", "setup.cfg"),
        regex=re.compile(r"python_requires\s*=\s*[\"']?([^\"'\s,]+)"),
    ),
    VersionRule(source=".python-version", patterns=(".python-version",), regex=re.compile(r"^\s*(\d+\.\d+(?:\.\d+)?)")),
    VersionRule(source="runtime.txt", patterns=("runtime.txt",), regex=re.compile(r"python-(\d+\.\d+(?:\.\d+)?)")),
    VersionRule(
        source="Pipfile", patterns=("Pipfile",), regex=re.compile(r"python_(?:full_)?version\s*=\s*[\"']([^\"']+)")
    ),
    VersionRule(
        source="container image",
        patterns=("Dockerfile", "Dockerfile.*", "*.dockerfile", "Containerfile"),
        regex=re.compile(r"^\s*FROM\s+(?:\S*/)?python:(\d+\.\d+[^\s]*)", re.IGNORECASE),
    ),
    VersionRule(
        source="CI image",
        patterns=(".gitlab-ci.yml", "*.gitlab-ci.yml", ".github/workflows/*.yml", ".github/workflows/*.yaml"),
        regex=re.compile(r"image:\s*[\"']?(?:\S*/)?python:(\d+\.\d+[^\s\"']*)"),
    ),
    VersionRule(
        source="CI python-version",
        patterns=(".github/workflows/*.yml", ".github/workflows/*.yaml", ".gitlab-ci.yml"),
        regex=re.compile(r"python[-_]version:\s*(.+)$"),
    ),
    VersionRule(source="tox envlist", patterns=("tox.ini",), regex=re.compile(r"^\s*envlist\s*=\s*(.+)$")),
]

_MINOR = re.compile(r"3\.(\d{1,2})")
_TOX_ENV = re.compile(r"py3(\d{1,2})")


class VersionDeclaration(BaseModel):
    source: str
    path: str
    line: int
    value: str
    minor_versions: list[str]


class PythonVersionAnalyzer(Analyzer):
    name = "python_versions"
    description = (
        "Finds declared Python versions in pyproject.toml, setup.py/cfg, .python-version, runtime.txt, Pipfile, "
        "Dockerfiles, CI configuration and tox.ini. Reports each declaration and the lowest declared 3.x version."
    )

    def analyze(self, target: AnalysisTarget) -> AnalyzerReport:
        declarations = [
            declaration
            for rule in _RULES
            for path in target.matching(*rule.patterns)
            for declaration in _declarations(target, rule, path)
        ]
        versions = sorted({v for d in declarations for v in d.minor_versions}, key=_minor_key)
        summary = {
            "declared_versions": versions,
            "lowest_declared_version": versions[0] if versions else None,
            "declarations": [d.model_dump() for d in declarations],
        }
        evidence = [
            target.file_evidence(
                FileFinding(
                    statement=f"{d.source} declares Python {d.value}",
                    path=d.path,
                    line=d.line,
                    excerpt=d.value,
                )
            )
            for d in declarations
        ]
        return self.report(target, summary, evidence)


def _declarations(target: AnalysisTarget, rule: VersionRule, path: str) -> list[VersionDeclaration]:
    text = target.read(path) or ""
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        if (match := rule.regex.search(line)) and (minors := _minor_versions(match.group(1))):
            found.append(
                VersionDeclaration(
                    source=rule.source,
                    path=path,
                    line=number,
                    value=match.group(1).strip(),
                    minor_versions=minors,
                )
            )
    return found


def _minor_versions(value: str) -> list[str]:
    minors = {f"3.{m}" for m in _MINOR.findall(value)} | {f"3.{m}" for m in _TOX_ENV.findall(value)}
    return sorted(minors, key=_minor_key)


def _minor_key(version: str) -> int:
    return int(version.split(".")[1])
