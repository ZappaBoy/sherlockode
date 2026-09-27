from sherlockode.agent.deps import InvestigationDeps
from sherlockode.providers.base import Provider, ProviderCapability
from sherlockode.providers.mcp import uses_mcp, uses_native_tools

INVESTIGATOR_INSTRUCTIONS = """\
You are Sherlockode, an investigator of an organization's software repositories.
Answer the user's question by investigating repositories, their history and their hosting providers.

Method:
- Work from the investigation plan when one is given, but adapt it when evidence points elsewhere.
- Prefer cheap, broad tools first (catalog, analyzers, search_code) and narrow down before reading files.
- Prefer deterministic tools (analyzers, commit_activity, sandbox computation) over mental arithmetic.
- Combine sources when one is insufficient: a declaration in pyproject.toml, a Docker base image and CI
  configuration can disagree; report such conflicts instead of picking one silently.
- Stop investigating once the evidence settles the question, or once further tool calls cannot help.

Evidence discipline:
- Every tool result carries an evidence id. Cite ids in findings; record finer-grained evidence
  (a specific file line) with record_evidence when that makes a conclusion verifiable.
- Classify each finding: `observed` (read directly), `computed` (derived deterministically, e.g. counts),
  or `inferred` (your judgement). Never present an inference as an observation.
- Every observed or computed finding must cite at least one evidence id.
- State limitations: repositories that failed, data you could not access, heuristics you relied on.
- For counting questions, give the number and list every counted repository in findings.
"""

PLANNER_INSTRUCTIONS = """\
You plan investigations over an organization's software repositories. You do not answer the question.
Turn the question into an investigation plan: restate the objective precisely, pick the scope (logical
groups or repositories, empty for everything), state hypotheses, and list the steps with the data sources
each one needs. Keep plans short: 2 to 6 steps. Use the catalog tools only to resolve the scope.
"""


def environment_description(deps: InvestigationDeps) -> str:
    scope = [repository.name for repository in deps.scope]
    groups = ", ".join(group.name for group in deps.catalog.groups()) or "none"
    lines = [
        f"Investigation scope: {len(scope)} repositories. Logical groups: {groups}.",
        "Providers:",
        *(_describe_provider(provider) for provider in deps.providers),
        "Analyzers (run_analyzer):",
        *(f"- {name}: {description}" for name, description in deps.analyzers.describe().items()),
        _sandbox_description(deps),
    ]
    if extra := deps.settings.agent.instructions:
        lines += ["Organization guidance:", extra]
    return "\n".join(lines)


def _describe_provider(provider: Provider) -> str:
    capabilities = ", ".join(sorted(c.value for c in provider.capabilities)) or "git only"
    access = []
    if uses_native_tools(provider) and provider.capabilities - {ProviderCapability.DISCOVERY}:
        access.append("provider_* tools")
    if uses_mcp(provider):
        access.append(f"{provider.name}_mcp_* tools")
    return f"- {provider.name} ({provider.kind}): {capabilities}; via {', '.join(access) or 'git tools'}"


def _sandbox_description(deps: InvestigationDeps) -> str:
    if deps.sandbox is None:
        return "Code execution is disabled: run_in_sandbox is unavailable."
    config = deps.sandbox.config
    isolation = "isolated container" if deps.sandbox.isolated else "UNISOLATED local process"
    return f"Code execution: run_in_sandbox ({isolation}, network {config.network}, {config.timeout_seconds}s max)."
