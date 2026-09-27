import asyncio
from pathlib import Path

from pydantic import BaseModel

from sherlockcode.concurrency import bounded_gather
from sherlockcode.domain.repository import RepositoryRef
from sherlockcode.git.client import GitClient
from sherlockcode.git.models import CloneRequest
from sherlockcode.providers.registry import ProviderSet
from sherlockcode.workspace.layout import Workspace


class SyncOutcome(BaseModel):
    repository: str
    path: Path | None = None
    error: str | None = None


# Clones and updates repository checkouts under the workspace.
class CheckoutManager:
    def __init__(self, workspace: Workspace, git: GitClient, providers: ProviderSet, clone_depth: int | None) -> None:
        self._workspace = workspace
        self._git = git
        self._providers = providers
        self._clone_depth = clone_depth
        self._locks: dict[Path, asyncio.Lock] = {}

    @property
    def repositories_root(self) -> Path:
        # Root directory under which every repository is checked out, e.g. as a CLI agent's working directory.
        return self._workspace.repositories

    def is_cloned(self, repository: RepositoryRef) -> bool:
        return _git_dir(self._workspace.checkout_path(repository)).exists()

    async def ensure(self, repository: RepositoryRef) -> Path:
        # Return the checkout, cloning it first if it isn't present yet. Never fetches an existing checkout.
        checkout = self._workspace.checkout_path(repository)
        async with self._lock_for(checkout):
            if not _git_dir(checkout).exists():
                await self._clone(repository, checkout)
        return checkout

    async def sync(self, repositories: list[RepositoryRef]) -> list[SyncOutcome]:
        # Clone missing checkouts and fetch existing ones, isolating failures per repository.

        async def run(repository: RepositoryRef) -> SyncOutcome:
            checkout = self._workspace.checkout_path(repository)
            try:
                async with self._lock_for(checkout):
                    if _git_dir(checkout).exists():
                        credentials = self._providers.for_repository(repository).git_credentials()
                        await self._git.fetch(checkout, credentials)
                    else:
                        await self._clone(repository, checkout)
            except Exception as error:
                return SyncOutcome(repository=repository.name, error=f"{type(error).__name__}: {error}")
            return SyncOutcome(repository=repository.name, path=checkout)

        return await bounded_gather(repositories, run)

    async def _clone(self, repository: RepositoryRef, checkout: Path) -> None:
        credentials = self._providers.for_repository(repository).git_credentials()
        request = CloneRequest(
            url=repository.url, destination=checkout, credentials=credentials, depth=self._clone_depth
        )
        await self._git.clone(request)

    def _lock_for(self, checkout: Path) -> asyncio.Lock:
        return self._locks.setdefault(checkout, asyncio.Lock())


def _git_dir(checkout: Path) -> Path:
    return checkout / ".git"
