import fnmatch
import logging
from collections import Counter
from collections.abc import Iterable

from pydantic import BaseModel

from sherlockcode.config.models import GroupDefinition, RepositoriesConfig, RepositoriesMode, RepositoryDefinition
from sherlockcode.domain.repository import RepositoryRef
from sherlockcode.providers.base import Provider, RepositoryDiscovery, repository_name_from_url
from sherlockcode.providers.registry import ProviderSet

logger = logging.getLogger(__name__)

ALL_SCOPE = "all"


class GroupSummary(BaseModel):
    name: str
    description: str | None
    repositories: list[str]


class UnknownScopeError(LookupError):
    def __init__(self, names: Iterable[str]) -> None:
        super().__init__(f"unknown groups or repositories: {', '.join(sorted(names))}")


class CatalogSources(BaseModel):
    repositories: RepositoriesConfig
    groups: dict[str, GroupDefinition]
    default_scope: list[str]


# The set of repositories the agent may investigate, and the logical groups over them.
class RepositoryCatalog:
    def __init__(self, repositories: list[RepositoryRef], sources: CatalogSources) -> None:
        self._repositories = {repository.name: repository for repository in _disambiguate(repositories)}
        self._sources = sources

    @classmethod
    async def load(cls, sources: CatalogSources, providers: ProviderSet) -> "RepositoryCatalog":
        explicit = [_from_definition(definition, providers) for definition in sources.repositories.definitions()]
        discovered = (
            []
            if sources.repositories.mode == RepositoriesMode.EXPLICIT
            else [repository for provider in providers for repository in await _discover(provider)]
        )
        known_urls = {repository.url for repository in explicit}
        candidates = explicit + [repository for repository in discovered if repository.url not in known_urls]
        excluded = sources.repositories.exclude
        return cls([r for r in candidates if not _matches_any(r, excluded)], sources)

    @property
    def repositories(self) -> list[RepositoryRef]:
        return list(self._repositories.values())

    def get(self, name: str) -> RepositoryRef:
        repository = self._repositories.get(name) or self._by_path(name)
        if repository is None:
            raise UnknownScopeError([name])
        return repository

    def groups(self) -> list[GroupSummary]:
        return [
            GroupSummary(
                name=name,
                description=definition.description,
                repositories=[r.name for r in self._members(definition)],
            )
            for name, definition in self._sources.groups.items()
        ]

    def resolve_scope(self, names: list[str]) -> list[RepositoryRef]:
        # Expand group and repository names into repositories. An empty scope uses the default scope.
        requested = names or self._sources.default_scope or [ALL_SCOPE]
        if ALL_SCOPE in requested:
            return self.repositories
        selected: dict[str, RepositoryRef] = {}
        unknown: list[str] = []
        for name in requested:
            members = self._expand(name)
            if members is None:
                unknown.append(name)
            selected |= {member.name: member for member in members or []}
        if unknown:
            raise UnknownScopeError(unknown)
        return list(selected.values())

    def _expand(self, name: str) -> list[RepositoryRef] | None:
        if name in self._sources.groups:
            return self._members(self._sources.groups[name])
        repository = self._repositories.get(name) or self._by_path(name)
        return [repository] if repository else None

    def _members(self, group: GroupDefinition) -> list[RepositoryRef]:
        explicit = set(group.repositories)
        return [
            repository
            for repository in self._repositories.values()
            if explicit & {repository.name, repository.full_path, repository.url}
            or (group.has_selectors and _matches_selectors(repository, group))
        ]

    def _by_path(self, full_path: str) -> RepositoryRef | None:
        return next((r for r in self._repositories.values() if full_path in (r.full_path, r.url)), None)


def _from_definition(definition: RepositoryDefinition, providers: ProviderSet) -> RepositoryRef:
    return RepositoryRef(
        name=definition.name or repository_name_from_url(definition.url),
        url=definition.url,
        provider=definition.provider or providers.resolve_name(definition.url),
        full_path=definition.full_path,
        default_branch=definition.default_branch,
        tags=frozenset(definition.tags),
    )


async def _discover(provider: Provider) -> list[RepositoryRef]:
    if not isinstance(provider, RepositoryDiscovery):
        return []
    try:
        repositories = await provider.discover_repositories()
    except Exception:
        logger.exception("repository discovery failed for provider %s", provider.name)
        return []
    return [repository for repository in repositories if not _matches_any(repository, provider.config.exclude)]


def _disambiguate(repositories: list[RepositoryRef]) -> list[RepositoryRef]:
    counts = Counter(repository.name for repository in repositories)
    return [
        repository.model_copy(update={"name": f"{repository.provider}:{repository.full_path or repository.url}"})
        if counts[repository.name] > 1
        else repository
        for repository in repositories
    ]


def _matches_any(repository: RepositoryRef, patterns: list[str]) -> bool:
    candidates = [value for value in (repository.name, repository.full_path, repository.url) if value]
    return any(fnmatch.fnmatch(value, pattern) for pattern in patterns for value in candidates)


def _matches_selectors(repository: RepositoryRef, group: GroupDefinition) -> bool:
    namespace = repository.namespace or ""
    checks = [
        not group.patterns or _matches_any(repository, group.patterns),
        not group.tags or bool(repository.tags & set(group.tags)),
        not group.providers or repository.provider in group.providers,
        not group.namespaces or any(fnmatch.fnmatch(namespace, pattern) for pattern in group.namespaces),
    ]
    return all(checks)
