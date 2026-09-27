from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from pydantic import BaseModel, ConfigDict, PrivateAttr

from sherlockode.analysis.registry import AnalyzerRegistry, default_analyzers
from sherlockode.catalog.catalog import CatalogSources, RepositoryCatalog
from sherlockode.config.settings import Settings
from sherlockode.git.client import GitClient
from sherlockode.providers.registry import ProviderRegistry, ProviderSet, default_registry
from sherlockode.sandbox.base import Sandbox
from sherlockode.sandbox.factory import build_sandbox
from sherlockode.workspace.layout import Workspace
from sherlockode.workspace.repositories import CheckoutManager


class Application(BaseModel):
    """Composition root wiring configuration, providers, workspace, git and sandbox together."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    settings: Settings
    workspace: Workspace
    providers: ProviderSet
    git: GitClient
    checkouts: CheckoutManager
    analyzers: AnalyzerRegistry
    sandbox: Sandbox | None
    _catalog: RepositoryCatalog | None = PrivateAttr(default=None)

    @classmethod
    @asynccontextmanager
    async def open(cls, settings: Settings, registry: ProviderRegistry | None = None) -> AsyncIterator["Application"]:
        workspace = Workspace(settings.workspace)
        workspace.initialize()
        providers = ProviderSet.from_config(settings.providers, registry or default_registry())
        git = GitClient(timeout_seconds=settings.limits.git_timeout_seconds)
        try:
            yield cls(
                settings=settings,
                workspace=workspace,
                providers=providers,
                git=git,
                checkouts=CheckoutManager(workspace, git, providers, settings.limits.clone_depth),
                analyzers=default_analyzers(),
                sandbox=build_sandbox(settings.sandbox, workspace.root),
            )
        finally:
            await providers.aclose()

    async def catalog(self) -> RepositoryCatalog:
        if self._catalog is None:
            sources = CatalogSources(
                repositories=self.settings.repositories,
                groups=self.settings.groups,
                default_scope=self.settings.agent.default_scope,
            )
            self._catalog = await RepositoryCatalog.load(sources, self.providers)
        return self._catalog
