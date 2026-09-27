from typing import Any

from pydantic_ai import AbstractToolset, Agent, ModelRetry, RunContext
from pydantic_ai.settings import ModelSettings

from sherlockode.agent.deps import InvestigationDeps
from sherlockode.agent.prompts import INVESTIGATOR_INSTRUCTIONS, PLANNER_INSTRUCTIONS, environment_description
from sherlockode.agent.toolsets.analysis import build_analysis_toolset, build_sandbox_toolset
from sherlockode.agent.toolsets.catalog import build_catalog_toolset
from sherlockode.agent.toolsets.evidence import build_evidence_toolset
from sherlockode.agent.toolsets.git import build_git_toolset
from sherlockode.agent.toolsets.provider import build_provider_toolset
from sherlockode.agent.toolsets.recording import RecordingToolset
from sherlockode.config.models import AgentConfig
from sherlockode.domain.evidence import EvidenceKind
from sherlockode.investigation.models import InvestigationAnswer, InvestigationPlan
from sherlockode.providers.mcp import build_mcp_toolset, uses_mcp
from sherlockode.providers.registry import ProviderSet


def _model_settings(config: AgentConfig) -> ModelSettings | None:
    return ModelSettings(temperature=config.temperature) if config.temperature is not None else None


def _environment(ctx: RunContext[InvestigationDeps]) -> str:
    return environment_description(ctx.deps)


def build_toolsets(providers: ProviderSet, sandbox_enabled: bool) -> list[AbstractToolset[InvestigationDeps]]:
    native = [
        build_catalog_toolset(),
        build_git_toolset(),
        build_provider_toolset(),
        build_analysis_toolset(),
        build_evidence_toolset(),
    ]
    if sandbox_enabled:
        native.append(build_sandbox_toolset())
    mcp: list[AbstractToolset[Any]] = [build_mcp_toolset(p) for p in providers if uses_mcp(p)]
    return [RecordingToolset(toolset) for toolset in [*native, *mcp]]


def build_investigator(
    config: AgentConfig, toolsets: list[AbstractToolset[InvestigationDeps]]
) -> Agent[InvestigationDeps, InvestigationAnswer]:
    agent = Agent(
        config.model,
        deps_type=InvestigationDeps,
        output_type=InvestigationAnswer,
        instructions=[INVESTIGATOR_INSTRUCTIONS, _environment],
        toolsets=toolsets,
        model_settings=_model_settings(config),
        retries=2,
        name="investigator",
        defer_model_check=True,
    )

    @agent.output_validator
    def require_evidence(ctx: RunContext[InvestigationDeps], answer: InvestigationAnswer) -> InvestigationAnswer:
        problems = []
        for finding in answer.findings:
            unknown = [eid for eid in finding.evidence_ids if not ctx.deps.recorder.has_evidence(eid)]
            if unknown:
                problems.append(f"'{finding.statement}' cites unknown evidence ids {unknown}")
            if finding.kind is not EvidenceKind.INFERRED and not finding.evidence_ids:
                problems.append(f"'{finding.statement}' is {finding.kind.value} but cites no evidence")
        if problems:
            raise ModelRetry("Fix the findings: " + "; ".join(problems))
        return answer

    return agent


def build_planner(config: AgentConfig) -> Agent[InvestigationDeps, InvestigationPlan]:
    return Agent(
        config.planner_model or config.model,
        deps_type=InvestigationDeps,
        output_type=InvestigationPlan,
        instructions=[PLANNER_INSTRUCTIONS, _environment],
        toolsets=[RecordingToolset(build_catalog_toolset())],
        model_settings=_model_settings(config),
        name="planner",
        defer_model_check=True,
    )
