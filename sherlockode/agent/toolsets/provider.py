from datetime import datetime

from pydantic import BaseModel, Field
from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from sherlockode.agent.deps import InvestigationDeps, Observation
from sherlockode.domain.activity import ChangeRequest, Contributor, Issue, WorkItemQuery, WorkItemState
from sherlockode.domain.evidence import EvidenceDraft, EvidenceKind, EvidenceSource, SourceKind
from sherlockode.domain.repository import Namespace, RepositoryMetadata, RepositoryRef
from sherlockode.providers.base import (
    ApiRequest,
    ApiResponse,
    ChangeRequestSource,
    ContributorSource,
    IssueSource,
    NamespaceSource,
    Provider,
    RawApiAccess,
    RepositoryMetadataSource,
)
from sherlockode.providers.mcp import uses_native_tools


class WorkItemFilter(BaseModel):
    state: WorkItemState = WorkItemState.ALL
    since: datetime | None = Field(default=None, description="Only items updated at or after this time.")
    limit: int = Field(default=100, ge=1, le=1000)


# Resolves the provider serving a repository and checks it offers a capability natively.
class ProviderAccess[C]:
    def __init__(self, deps: InvestigationDeps, capability: type[C]) -> None:
        self._deps = deps
        self._capability = capability

    def for_repository(self, name: str) -> tuple[RepositoryRef, C]:
        repository = self._deps.repository(name)
        return repository, self._require(self._deps.providers.for_repository(repository))

    def by_name(self, name: str) -> C:
        try:
            return self._require(self._deps.providers.get(name))
        except KeyError as error:
            raise ModelRetry(str(error)) from None

    def _require(self, provider: Provider) -> C:
        if not uses_native_tools(provider):
            raise ModelRetry(f"provider '{provider.name}' is served by its MCP tools ({provider.name}_mcp_*)")
        if not isinstance(provider, self._capability):
            raise ModelRetry(
                f"provider '{provider.name}' ({provider.kind}) cannot do this; use git tools for git-hosted data"
            )
        return provider


def _api_evidence(provider: str, repository: str | None, endpoint: str, statement: str) -> EvidenceDraft:
    return EvidenceDraft(
        kind=EvidenceKind.OBSERVED,
        statement=statement,
        source=EvidenceSource(
            kind=SourceKind.PROVIDER_API, provider=provider, repository=repository, endpoint=endpoint
        ),
    )


def build_provider_toolset() -> FunctionToolset[InvestigationDeps]:
    toolset = FunctionToolset[InvestigationDeps]()

    @toolset.tool(
        description="Hosting metadata: description, visibility, archived flag, languages, topics, activity timestamps."
    )
    async def provider_repository_metadata(
        ctx: RunContext[InvestigationDeps], repository: str
    ) -> Observation[RepositoryMetadata]:
        ref, provider = ProviderAccess(ctx.deps, RepositoryMetadataSource).for_repository(repository)
        metadata = await provider.repository_metadata(ref)
        return ctx.deps.observe(
            metadata, _api_evidence(ref.provider, ref.name, "repository", f"{ref.name}: repository metadata")
        )

    @toolset.tool(description="Contributors and their contribution counts as reported by the hosting provider.")
    async def provider_contributors(
        ctx: RunContext[InvestigationDeps], repository: str
    ) -> Observation[list[Contributor]]:
        ref, provider = ProviderAccess(ctx.deps, ContributorSource).for_repository(repository)
        contributors = await provider.contributors(ref)
        statement = f"{ref.name}: {len(contributors)} contributors"
        return ctx.deps.observe(contributors, _api_evidence(ref.provider, ref.name, "contributors", statement))

    @toolset.tool(description="Pull requests (GitHub) or merge requests (GitLab), most recently updated first.")
    async def provider_change_requests(
        ctx: RunContext[InvestigationDeps], repository: str, criteria: WorkItemFilter
    ) -> Observation[list[ChangeRequest]]:
        ref, provider = ProviderAccess(ctx.deps, ChangeRequestSource).for_repository(repository)
        items = await provider.change_requests(ref, WorkItemQuery(repository=ref.name, **criteria.model_dump()))
        statement = f"{ref.name}: {len(items)} change requests ({criteria.state.value})"
        return ctx.deps.observe(items, _api_evidence(ref.provider, ref.name, "change_requests", statement))

    @toolset.tool(description="Issues, most recently updated first.")
    async def provider_issues(
        ctx: RunContext[InvestigationDeps], repository: str, criteria: WorkItemFilter
    ) -> Observation[list[Issue]]:
        ref, provider = ProviderAccess(ctx.deps, IssueSource).for_repository(repository)
        items = await provider.issues(ref, WorkItemQuery(repository=ref.name, **criteria.model_dump()))
        statement = f"{ref.name}: {len(items)} issues ({criteria.state.value})"
        return ctx.deps.observe(items, _api_evidence(ref.provider, ref.name, "issues", statement))

    @toolset.tool(description="Organizations (GitHub) or groups (GitLab) configured or visible for a provider.")
    async def provider_namespaces(ctx: RunContext[InvestigationDeps], provider: str) -> Observation[list[Namespace]]:
        source = ProviderAccess(ctx.deps, NamespaceSource).by_name(provider)
        namespaces = await source.namespaces()
        statement = f"{provider}: {len(namespaces)} namespaces"
        return ctx.deps.observe(namespaces, _api_evidence(provider, None, "namespaces", statement))

    @toolset.tool(
        description=(
            "Read-only GET against a provider REST API, for data the other tools do not cover. "
            "Paths are relative to the API root, e.g. `repos/org/name/releases` (GitHub REST v3) or "
            "`projects/group%2Fname/pipelines` (GitLab REST v4). List endpoints are paginated up to max_items."
        )
    )
    async def provider_api_get(
        ctx: RunContext[InvestigationDeps], provider: str, request: ApiRequest
    ) -> Observation[ApiResponse]:
        source = ProviderAccess(ctx.deps, RawApiAccess).by_name(provider)
        response = await source.api_get(request)
        statement = f"{provider}: GET {request.path} -> {response.status_code}"
        return ctx.deps.observe(response, _api_evidence(provider, None, f"GET {request.path}", statement))

    return toolset
