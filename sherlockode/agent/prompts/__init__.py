from dataclasses import dataclass
from typing import TYPE_CHECKING

from jinja2 import Environment, PackageLoader, StrictUndefined

from sherlockode.providers.base import Provider, ProviderCapability
from sherlockode.providers.mcp import uses_mcp, uses_native_tools

if TYPE_CHECKING:
    from sherlockode.agent.deps import InvestigationDeps
    from sherlockode.investigation.models import InvestigationPlan, InvestigationRequest

_ENV = Environment(
    loader=PackageLoader("sherlockode.agent.prompts", "templates"),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
)


def _render(template_name: str, **context: object) -> str:
    return _ENV.get_template(template_name).render(**context)


def investigator_instructions() -> str:
    return _render("investigator.md.jinja")


def planner_instructions() -> str:
    return _render("planner.md.jinja")


@dataclass
class ProviderView:
    name: str
    kind: str
    capabilities: str
    access: str


def _provider_view(provider: Provider) -> ProviderView:
    capabilities = ", ".join(sorted(c.value for c in provider.capabilities)) or "git only"
    access = []
    if uses_native_tools(provider) and provider.capabilities - {ProviderCapability.DISCOVERY}:
        access.append("provider_* tools")
    if uses_mcp(provider):
        access.append(f"{provider.name}_mcp_* tools")
    return ProviderView(
        name=provider.name,
        kind=provider.kind,
        capabilities=capabilities,
        access=", ".join(access) or "git tools",
    )


def _sandbox_description(deps: "InvestigationDeps") -> str:
    if deps.sandbox is None:
        return "Code execution is disabled: run_in_sandbox is unavailable."
    config = deps.sandbox.config
    isolation = "isolated container" if deps.sandbox.isolated else "UNISOLATED local process"
    return f"Code execution: run_in_sandbox ({isolation}, network {config.network}, {config.timeout_seconds}s max)."


def environment_description(deps: "InvestigationDeps") -> str:
    return _render(
        "environment.md.jinja",
        scope_count=len(deps.scope),
        groups=", ".join(group.name for group in deps.catalog.groups()) or "none",
        providers=[_provider_view(provider) for provider in deps.providers],
        analyzers=deps.analyzers.describe(),
        sandbox_description=_sandbox_description(deps),
        extra_instructions=deps.settings.agent.instructions,
    )


def investigation_prompt(request: "InvestigationRequest", plan: "InvestigationPlan | None") -> str:
    return _render(
        "investigation_prompt.md.jinja",
        question=request.question,
        scope=request.scope,
        plan_json=plan.model_dump_json(indent=2) if plan else None,
    )


def cli_agent_prompt(
    request: "InvestigationRequest",
    plan: "InvestigationPlan | None",
    deps: "InvestigationDeps",
    schema_json: str,
) -> str:
    return _render(
        "cli_agent.md.jinja",
        question=request.question,
        scope=request.scope,
        plan_json=plan.model_dump_json(indent=2) if plan else None,
        environment=environment_description(deps),
        schema_json=schema_json,
        repositories=[repository.name for repository in deps.scope],
    )
