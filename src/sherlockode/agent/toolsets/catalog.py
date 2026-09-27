import fnmatch

from pydantic import BaseModel
from pydantic_ai import FunctionToolset, RunContext

from sherlockode.agent.deps import InvestigationDeps
from sherlockode.catalog.catalog import GroupSummary


class RepositorySummary(BaseModel):
    name: str
    provider: str
    full_path: str | None
    url: str
    tags: list[str]
    cloned: bool


def build_catalog_toolset() -> FunctionToolset[InvestigationDeps]:
    toolset = FunctionToolset[InvestigationDeps]()

    @toolset.tool
    def list_repositories(
        ctx: RunContext[InvestigationDeps], groups: list[str] | None = None, name_pattern: str | None = None
    ) -> list[RepositorySummary]:
        """List repositories in the investigation scope.

        Args:
            groups: Restrict to these logical groups or repository names.
            name_pattern: Glob matched against repository name or full path, e.g. `*-service`.
        """
        repositories = ctx.deps.repositories(groups or [])
        if name_pattern:
            repositories = [
                r
                for r in repositories
                if fnmatch.fnmatch(r.name, name_pattern) or fnmatch.fnmatch(r.full_path or "", name_pattern)
            ]
        return [
            RepositorySummary(
                name=r.name,
                provider=r.provider,
                full_path=r.full_path,
                url=r.url,
                tags=sorted(r.tags),
                cloned=ctx.deps.checkouts.is_cloned(r),
            )
            for r in repositories
        ]

    @toolset.tool
    def list_groups(ctx: RunContext[InvestigationDeps]) -> list[GroupSummary]:
        """List the user-defined logical repository groups and their members."""
        return ctx.deps.catalog.groups()

    return toolset
