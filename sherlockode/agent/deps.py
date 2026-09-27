from collections.abc import Awaitable, Callable

from pydantic import BaseModel, ConfigDict
from pydantic_ai import ModelRetry

from sherlockode.analysis.registry import AnalyzerRegistry
from sherlockode.catalog.catalog import RepositoryCatalog, UnknownScopeError
from sherlockode.concurrency import bounded_gather
from sherlockode.config.settings import Settings
from sherlockode.domain.evidence import EvidenceDraft
from sherlockode.domain.repository import RepositoryRef
from sherlockode.git.client import GitClient
from sherlockode.investigation.recorder import InvestigationRecorder
from sherlockode.providers.registry import ProviderSet
from sherlockode.sandbox.base import Sandbox
from sherlockode.workspace.repositories import CheckoutManager


# Services available to agent tools during one investigation.
class InvestigationDeps(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    settings: Settings
    catalog: RepositoryCatalog
    providers: ProviderSet
    git: GitClient
    checkouts: CheckoutManager
    analyzers: AnalyzerRegistry
    sandbox: Sandbox | None
    recorder: InvestigationRecorder
    scope: list[RepositoryRef]

    def observe[T](self, data: T, draft: EvidenceDraft) -> "Observation[T]":
        return Observation(evidence_id=self.recorder.record(draft).id, data=data)

    def repository(self, name: str) -> RepositoryRef:
        # Resolve a repository name within the investigation scope, or ask the model to correct it.
        allowed = {repository.name: repository for repository in self.scope}
        try:
            repository = self.catalog.get(name)
        except UnknownScopeError:
            raise ModelRetry(f"unknown repository '{name}'. Use list_repositories to find valid names.") from None
        if repository.name not in allowed:
            raise ModelRetry(f"repository '{name}' is outside the investigation scope")
        return repository

    def repositories(self, names: list[str]) -> list[RepositoryRef]:
        # Resolve group or repository names within scope. An empty list means the whole scope.
        if not names:
            selected = self.scope
        else:
            try:
                resolved = self.catalog.resolve_scope(names)
            except UnknownScopeError as error:
                raise ModelRetry(str(error)) from None
            allowed = {repository.name for repository in self.scope}
            selected = [repository for repository in resolved if repository.name in allowed]
        limit = self.settings.limits.max_repositories
        if len(selected) > limit:
            raise ModelRetry(f"{len(selected)} repositories selected, the limit is {limit}. Narrow the selection.")
        return selected


class Observation[T](BaseModel):
    evidence_id: str
    data: T


class RepositoryResult[T](BaseModel):
    repository: str
    evidence_id: str | None = None
    data: T | None = None
    error: str | None = None


# Run an action on each repository with bounded concurrency, isolating per-repository failures.
async def per_repository[T](
    repositories: list[RepositoryRef], action: Callable[[RepositoryRef], Awaitable[Observation[T]]]
) -> list[RepositoryResult[T]]:
    async def run(repository: RepositoryRef) -> RepositoryResult[T]:
        try:
            observation = await action(repository)
        except ModelRetry:
            raise
        except Exception as error:
            return RepositoryResult(repository=repository.name, error=f"{type(error).__name__}: {error}")
        return RepositoryResult(repository=repository.name, evidence_id=observation.evidence_id, data=observation.data)

    return await bounded_gather(repositories, run)
