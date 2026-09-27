from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from sherlockode.domain.evidence import Evidence, EvidenceKind


class DataSource(StrEnum):
    CATALOG = "catalog"
    SOURCE_CODE = "source_code"
    GIT_HISTORY = "git_history"
    PROVIDER_API = "provider_api"
    ANALYZER = "analyzer"
    SANDBOX = "sandbox"


class PlanStep(BaseModel):
    id: str = Field(description="Short identifier such as P1, P2.")
    goal: str = Field(description="What this step establishes.")
    data_sources: list[DataSource] = Field(description="Kinds of data this step needs to consult.")
    repositories: list[str] = Field(default_factory=list, description="Groups or repositories, empty for all.")


class InvestigationPlan(BaseModel):
    objective: str = Field(description="The question restated as a precise, answerable objective.")
    scope: list[str] = Field(default_factory=list, description="Groups or repositories to investigate.")
    hypotheses: list[str] = Field(
        default_factory=list, description="Tentative explanations the investigation steps will confirm or refute."
    )
    steps: list[PlanStep] = Field(description="Ordered steps that gather the evidence needed to answer.")
    expected_evidence: list[str] = Field(default_factory=list, description="What evidence would settle the question.")


class Finding(BaseModel):
    statement: str = Field(description="A single significant claim, stated precisely.")
    kind: EvidenceKind = Field(description="observed, computed or inferred.")
    evidence_ids: list[str] = Field(default_factory=list, description="Ids of recorded evidence supporting it.")
    repositories: list[str] = Field(
        default_factory=list, description="Repositories this finding concerns, if specific to some."
    )


class InvestigationAnswer(BaseModel):
    answer: str = Field(description="Direct, concise answer to the question.")
    findings: list[Finding] = Field(description="Every significant claim, each backed by evidence ids.")
    limitations: list[str] = Field(default_factory=list, description="Gaps, assumptions, unverifiable parts.")


class StepStatus(StrEnum):
    OK = "ok"
    ERROR = "error"


class StepRecord(BaseModel):
    id: str
    tool: str
    arguments: dict[str, Any]
    started_at: datetime
    duration_seconds: float | None = None
    status: StepStatus | None = None
    error: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class InvestigationStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class InvestigationRequest(BaseModel):
    question: str
    scope: list[str] = Field(default_factory=list)
    planning: bool | None = None


class Manifest(BaseModel):
    id: str
    question: str
    requested_scope: list[str]
    resolved_scope: list[str]
    model: str
    planner_model: str | None
    version: str
    status: InvestigationStatus = InvestigationStatus.RUNNING
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    error: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    configuration: dict[str, Any] = Field(default_factory=dict)


class InvestigationReport(BaseModel):
    manifest: Manifest
    plan: InvestigationPlan | None
    answer: InvestigationAnswer
    evidence: list[Evidence]
    steps: list[StepRecord]
