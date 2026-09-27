import fnmatch
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from sherlockode.domain.evidence import EvidenceDraft, EvidenceKind, EvidenceSource, SourceKind
from sherlockode.domain.repository import RepositoryRef


class AnalysisTarget(BaseModel):
    repository: RepositoryRef
    checkout: Path
    files: list[str]
    commit: str
    max_file_bytes: int = 200_000

    def matching(self, *patterns: str) -> list[str]:
        return [
            path
            for path in self.files
            if any(fnmatch.fnmatch(path, p) or fnmatch.fnmatch(path.rsplit("/", 1)[-1], p) for p in patterns)
        ]

    def read(self, path: str) -> str | None:
        file = self.checkout / path
        if not file.is_file() or file.is_symlink() or file.stat().st_size > self.max_file_bytes:
            return None
        return file.read_text(encoding="utf-8", errors="replace")

    def file_evidence(self, finding: "FileFinding") -> EvidenceDraft:
        return EvidenceDraft(
            kind=EvidenceKind.OBSERVED,
            statement=finding.statement,
            excerpt=finding.excerpt,
            source=EvidenceSource(
                kind=SourceKind.FILE,
                repository=self.repository.name,
                path=finding.path,
                line=finding.line,
                commit=self.commit,
            ),
        )


class FileFinding(BaseModel):
    statement: str
    path: str
    line: int | None = None
    excerpt: str | None = None


class AnalyzerReport(BaseModel):
    repository: str
    analyzer: str
    commit: str
    summary: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceDraft] = Field(default_factory=list)


class Analyzer(ABC):
    """A deterministic, read-only analysis over a checkout. Never executes repository code."""

    name: str
    description: str

    @abstractmethod
    def analyze(self, target: AnalysisTarget) -> AnalyzerReport: ...

    def report(self, target: AnalysisTarget, summary: dict[str, Any], evidence: list[EvidenceDraft]) -> AnalyzerReport:
        return AnalyzerReport(
            repository=target.repository.name,
            analyzer=self.name,
            commit=target.commit,
            summary=summary,
            evidence=evidence,
        )


def line_of(text: str, needle: str) -> int | None:
    index = text.find(needle)
    return text.count("\n", 0, index) + 1 if index >= 0 else None
