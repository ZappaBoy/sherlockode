from pydantic import BaseModel, Field
from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from sherlockode.agent.deps import InvestigationDeps
from sherlockode.domain.evidence import EvidenceDraft, EvidenceKind, EvidenceSource, SourceKind


class EvidenceNote(BaseModel):
    kind: EvidenceKind
    statement: str = Field(description="The fact, result or inference, stated precisely.")
    repository: str | None = None
    path: str | None = None
    line: int | None = None
    commit: str | None = None
    excerpt: str | None = Field(default=None, description="Verbatim supporting text, e.g. the matched line.")
    based_on: list[str] = Field(default_factory=list, description="Evidence ids this derives from.")


def build_evidence_toolset() -> FunctionToolset[InvestigationDeps]:
    toolset = FunctionToolset[InvestigationDeps]()

    @toolset.tool
    def record_evidence(ctx: RunContext[InvestigationDeps], note: EvidenceNote) -> str:
        """Record a precise piece of evidence (e.g. a specific file line) or an inference, and get its id.

        Tool results already carry evidence ids; use this for finer-grained citations and for inferences.
        """
        if note.repository:
            ctx.deps.repository(note.repository)
        unknown = [eid for eid in note.based_on if not ctx.deps.recorder.has_evidence(eid)]
        if unknown:
            raise ModelRetry(f"unknown evidence ids {unknown}")
        source_kind = SourceKind.FILE if note.path else SourceKind.AGENT
        based_on = f" (based on {', '.join(note.based_on)})" if note.based_on else ""
        draft = EvidenceDraft(
            kind=note.kind,
            statement=note.statement + based_on,
            excerpt=note.excerpt,
            source=EvidenceSource(
                kind=source_kind,
                repository=note.repository,
                path=note.path,
                line=note.line,
                commit=note.commit,
            ),
        )
        return ctx.deps.recorder.record(draft).id

    return toolset
