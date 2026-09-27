from typing import Annotated, Any

from pydantic import BaseModel, Field
from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from sherlockode.agent.deps import InvestigationDeps, Observation, RepositoryResult, per_repository
from sherlockode.analysis.base import AnalysisTarget
from sherlockode.domain.evidence import EvidenceDraft, EvidenceKind, EvidenceSource, SourceKind
from sherlockode.domain.repository import RepositoryRef
from sherlockode.sandbox.base import ExecutionRequest, ExecutionResult, ScriptLanguage


class AnalyzerOutput(BaseModel):
    commit: str
    summary: dict[str, Any]
    evidence_ids: list[str] = Field(description="Evidence recorded for individual findings, in summary order.")


class SandboxRun(BaseModel):
    script: str = Field(description="Script body. The repository is the working directory, mounted read-only.")
    language: ScriptLanguage = ScriptLanguage.PYTHON
    repository: str | None = Field(default=None, description="Repository to mount; none for pure computation.")
    purpose: str = Field(description="One sentence describing what the script computes, kept for the audit trail.")
    timeout_seconds: int | None = None


class SandboxOutcome(BaseModel):
    run: str
    result: ExecutionResult


def build_analysis_toolset() -> FunctionToolset[InvestigationDeps]:
    toolset = FunctionToolset[InvestigationDeps]()

    @toolset.tool(
        description="Run a built-in, deterministic analyzer on repositories. Findings are recorded as evidence."
    )
    async def run_analyzer(
        ctx: RunContext[InvestigationDeps],
        analyzer: Annotated[str, Field(description="Analyzer name, see the instructions for the available analyzers.")],
        repositories: Annotated[list[str], Field(description="Groups or repositories; empty for the whole scope.")],
    ) -> list[RepositoryResult[AnalyzerOutput]]:
        try:
            selected = ctx.deps.analyzers.get(analyzer)
        except KeyError as error:
            raise ModelRetry(str(error)) from None

        async def analyze(repository: RepositoryRef) -> Observation[AnalyzerOutput]:
            checkout = await ctx.deps.checkouts.ensure(repository)
            target = AnalysisTarget(
                repository=repository,
                checkout=checkout,
                files=await ctx.deps.git.list_files(checkout),
                commit=await ctx.deps.git.head(checkout),
                max_file_bytes=ctx.deps.settings.limits.max_file_bytes,
            )
            report = selected.analyze(target)
            evidence_ids = [ctx.deps.recorder.record(draft).id for draft in report.evidence]
            output = AnalyzerOutput(commit=report.commit, summary=report.summary, evidence_ids=evidence_ids)
            summary = EvidenceDraft(
                kind=EvidenceKind.COMPUTED,
                statement=f"{repository.name}: analyzer {analyzer} summary {_brief(report.summary)}",
                source=EvidenceSource(
                    kind=SourceKind.ANALYZER,
                    repository=repository.name,
                    commit=report.commit,
                    command=analyzer,
                ),
            )
            return ctx.deps.observe(output, summary)

        return await per_repository(ctx.deps.repositories(repositories), analyze)

    return toolset


def build_sandbox_toolset() -> FunctionToolset[InvestigationDeps]:
    toolset = FunctionToolset[InvestigationDeps]()

    @toolset.tool(
        description=(
            "Execute a shell or Python script in a disposable, network-less, resource-limited sandbox. "
            "Use it for computations the other tools cannot do: parsing many files, statistics, custom analysis "
            "tools. Files written to $OUTPUT_DIR are kept as investigation artifacts. Never run repository code "
            "such as builds, tests or install scripts unless the question requires it."
        )
    )
    async def run_in_sandbox(ctx: RunContext[InvestigationDeps], run: SandboxRun) -> Observation[SandboxOutcome]:
        sandbox = ctx.deps.sandbox
        assert sandbox is not None
        checkout = None
        if run.repository:
            checkout = await ctx.deps.checkouts.ensure(ctx.deps.repository(run.repository))
        name = ctx.deps.recorder.next_sandbox_run()
        request = ExecutionRequest(
            script=run.script,
            language=run.language,
            repository=checkout,
            run_directory=ctx.deps.recorder.paths.sandbox_runs / name,
            timeout_seconds=run.timeout_seconds,
        )
        result = await sandbox.execute(request)
        draft = EvidenceDraft(
            kind=EvidenceKind.COMPUTED,
            statement=f"{run.purpose} (exit {result.exit_code})",
            excerpt=result.stdout[:500] or None,
            source=EvidenceSource(
                kind=SourceKind.COMMAND,
                repository=run.repository,
                command=f"sandbox/{name}/{run.language.filename}",
            ),
        )
        return ctx.deps.observe(SandboxOutcome(run=name, result=result), draft)

    return toolset


def _brief(summary: dict[str, Any]) -> str:
    return str({key: value for key, value in summary.items() if not isinstance(value, list)})[:300]
