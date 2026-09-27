from collections.abc import Callable, Iterator

from sherlockode.config.models import ProviderConfig, ProviderKind
from sherlockode.domain.repository import RepositoryRef
from sherlockode.providers.base import Provider, ProviderContext
from sherlockode.providers.generic import GenericGitProvider
from sherlockode.providers.github import GitHubProvider
from sherlockode.providers.gitlab import GitLabProvider

ProviderFactory = Callable[[ProviderContext], Provider]


class ProviderRegistry:
    """Maps provider kinds to implementations. New providers register here without touching the agent."""

    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}

    def register(self, kind: str, factory: ProviderFactory) -> None:
        self._factories[kind] = factory

    def create(self, name: str, config: ProviderConfig) -> Provider:
        factory = self._factories.get(config.kind)
        if factory is None:
            raise ValueError(f"unknown provider kind '{config.kind}' for provider '{name}'")
        return factory(ProviderContext(name=name, config=config))


def default_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(ProviderKind.GIT, GenericGitProvider)
    registry.register(ProviderKind.GITHUB, GitHubProvider)
    registry.register(ProviderKind.GITLAB, GitLabProvider)
    return registry


class ProviderSet:
    """The providers configured for this deployment."""

    def __init__(self, providers: dict[str, Provider], fallback: str) -> None:
        self._providers = providers
        self._fallback = fallback

    @classmethod
    def from_config(cls, configs: dict[str, ProviderConfig], registry: ProviderRegistry) -> "ProviderSet":
        providers = {name: registry.create(name, config) for name, config in configs.items()}
        fallback = next(name for name, provider in providers.items() if provider.kind == ProviderKind.GIT)
        return cls(providers, fallback)

    def __iter__(self) -> Iterator[Provider]:
        return iter(self._providers.values())

    def get(self, name: str) -> Provider:
        try:
            return self._providers[name]
        except KeyError:
            raise KeyError(f"unknown provider '{name}'") from None

    def for_repository(self, repository: RepositoryRef) -> Provider:
        return self.get(repository.provider)

    def resolve_name(self, url: str) -> str:
        return next((p.name for p in self._providers.values() if p.owns(url)), self._fallback)

    async def aclose(self) -> None:
        for provider in self._providers.values():
            await provider.aclose()
