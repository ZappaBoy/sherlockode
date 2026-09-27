import os
from typing import Any

from pydantic_ai import AbstractToolset, Agent, ModelRetry, RunContext
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from sherlockode.agent.deps import InvestigationDeps
from sherlockode.agent.prompts import environment_description, investigator_instructions, planner_instructions
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

_DUMMY_LOCAL_API_KEY = "not-needed"


def _model_settings(config: AgentConfig) -> ModelSettings | None:
    return ModelSettings(temperature=config.temperature) if config.temperature is not None else None


def resolve_model(model_name: str, config: AgentConfig) -> str | Model:
    # Turn a configured model name into a PydanticAI model, building an OpenAI-compatible client when
    # `base_url` points at a local or self-hosted server (Ollama, vLLM, LM Studio, llama.cpp, LiteLLM, ...).
    if config.base_url is None:
        return model_name
    name = model_name.removeprefix("openai:")
    api_key = os.environ.get(config.api_key_env, _DUMMY_LOCAL_API_KEY) if config.api_key_env else _DUMMY_LOCAL_API_KEY
    return OpenAIChatModel(name, provider=OpenAIProvider(base_url=config.base_url, api_key=api_key))


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
        resolve_model(config.model, config),
        deps_type=InvestigationDeps,
        output_type=InvestigationAnswer,
        instructions=[investigator_instructions(), _environment],
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
        resolve_model(config.planner_model or config.model, config),
        deps_type=InvestigationDeps,
        output_type=InvestigationPlan,
        instructions=[planner_instructions(), _environment],
        toolsets=[RecordingToolset(build_catalog_toolset())],
        model_settings=_model_settings(config),
        name="planner",
        defer_model_check=True,
    )
