from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class FactKind(str, Enum):
    OBSERVED = "observed"
    COMPUTED = "computed"
    INFERRED = "inferred"


class EvidenceReference(BaseModel):
    repository: str | None = None
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    commit_sha: str | None = None
    provider_source: str | None = None
    command: str | None = None


class EvidenceItem(BaseModel):
    fact_kind: FactKind
    statement: str
    references: list[EvidenceReference] = Field(default_factory=list)


class InvestigationStep(BaseModel):
    step_id: str
    description: str
    tool: str


class InvestigationPlan(BaseModel):
    question: str
    steps: list[InvestigationStep] = Field(default_factory=list)


class InvestigationResult(BaseModel):
    answer: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
