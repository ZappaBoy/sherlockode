from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class EvidenceKind(StrEnum):
    # Read directly from a source: a file, a commit, a provider API response.
    OBSERVED = "observed"
    # Deterministically derived from observations: counts, aggregations, analyzer results.
    COMPUTED = "computed"
    # A judgement made by the agent that is not mechanically verifiable.
    INFERRED = "inferred"


class SourceKind(StrEnum):
    FILE = "file"
    GIT = "git"
    PROVIDER_API = "provider_api"
    COMMAND = "command"
    ANALYZER = "analyzer"
    AGENT = "agent"


class EvidenceSource(BaseModel):
    kind: SourceKind
    repository: str | None = None
    path: str | None = None
    line: int | None = None
    commit: str | None = None
    provider: str | None = None
    endpoint: str | None = None
    command: str | None = None

    def describe(self) -> str:
        location = ":".join(str(part) for part in (self.path, self.line) if part is not None)
        parts = [
            self.repository,
            location or None,
            self.commit and f"@{self.commit[:12]}",
            self.endpoint and f"{self.provider or 'api'} {self.endpoint}",
            self.command and f"$ {self.command}",
        ]
        return " ".join(part for part in parts if part) or self.kind.value


class EvidenceDraft(BaseModel):
    kind: EvidenceKind
    statement: str
    source: EvidenceSource
    excerpt: str | None = None


class Evidence(EvidenceDraft):
    id: str
    step_id: str | None = None
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
