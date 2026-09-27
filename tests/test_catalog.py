import httpx
import pytest

from sherlockode.catalog.catalog import CatalogSources, RepositoryCatalog, UnknownScopeError
from sherlockode.config.models import (
    DiscoveryMode,
    GroupDefinition,
    ProviderConfig,
    RepositoriesConfig,
    RepositoriesMode,
)
from sherlockode.domain.repository import RepositoryRef
from sherlockode.providers.base import ProviderContext
from sherlockode.providers.github import GitHubProvider
from sherlockode.providers.http import ProviderHttpClient
from sherlockode.providers.registry import ProviderSet, default_registry


def _providers() -> ProviderSet:
    configs = {
        "git": ProviderConfig(kind="git"),
        "gitlab": ProviderConfig(kind="gitlab", base_url="https://gitlab.example.com/api/v4"),
        "github": ProviderConfig(kind="github"),
    }
    return ProviderSet.from_config(configs, default_registry())


async def _catalog(groups: dict[str, GroupDefinition], default_scope: list[str] | None = None) -> RepositoryCatalog:
    sources = CatalogSources(
        repositories=RepositoriesConfig(
            include=[
                "git@gitlab.example.com:platform/service-a.git",
                {"url": "https://github.com/example/service-b.git", "tags": ["python"]},
                "https://git.example.org/legacy/project-x.git",
                "https://github.com/example/service-a-archive.git",
            ],
            exclude=["*-archive"],
        ),
        groups=groups,
        default_scope=default_scope or [],
    )
    return await RepositoryCatalog.load(sources, _providers())


async def test_repositories_are_routed_to_providers_by_host() -> None:
    catalog = await _catalog({})

    providers = {repository.name: repository.provider for repository in catalog.repositories}

    assert providers == {"service-a": "gitlab", "service-b": "github", "project-x": "git"}


async def test_groups_combine_explicit_members_and_selectors() -> None:
    groups = {
        "python": GroupDefinition(repositories=["service-a"], tags=["python"]),
        "gitlab": GroupDefinition(providers=["gitlab"]),
        "legacy": GroupDefinition.model_validate(["project-x"]),
    }
    catalog = await _catalog(groups)

    members = {group.name: group.repositories for group in catalog.groups()}

    assert members == {"python": ["service-a", "service-b"], "gitlab": ["service-a"], "legacy": ["project-x"]}


async def test_scope_resolution_uses_default_scope() -> None:
    catalog = await _catalog({"legacy": GroupDefinition(repositories=["project-x"])}, default_scope=["legacy"])

    assert [r.name for r in catalog.resolve_scope([])] == ["project-x"]
    assert len(catalog.resolve_scope(["all"])) == 3
    assert [r.name for r in catalog.resolve_scope(["service-b", "legacy"])] == ["service-b", "project-x"]


async def test_unknown_scope_is_reported() -> None:
    catalog = await _catalog({})

    with pytest.raises(UnknownScopeError, match="nope"):
        catalog.resolve_scope(["nope"])


def _discovery_providers(exclude: list[str] | None = None) -> ProviderSet:
    def handler(request: httpx.Request) -> httpx.Response:
        data = [
            {"name": "keep", "clone_url": "https://github.com/o/keep.git", "full_name": "o/keep"},
            {"name": "skip", "clone_url": "https://github.com/o/skip.git", "full_name": "o/skip"},
        ]
        return httpx.Response(200, json=data)

    config = ProviderConfig(kind="github", discovery=DiscoveryMode.ALL, exclude=exclude or [])
    provider = GitHubProvider(ProviderContext(name="github", config=config))
    provider.http = ProviderHttpClient(
        httpx.AsyncClient(base_url=provider.base_url, transport=httpx.MockTransport(handler))
    )
    return ProviderSet({"github": provider}, "github")


async def test_provider_exclude_filters_discovered_repositories_only() -> None:
    sources = CatalogSources(repositories=RepositoriesConfig(), groups={}, default_scope=[])

    catalog = await RepositoryCatalog.load(sources, _discovery_providers(exclude=["skip"]))

    assert [r.name for r in catalog.repositories] == ["keep"]


async def test_repositories_mode_explicit_disables_all_provider_discovery() -> None:
    repositories = RepositoriesConfig(mode=RepositoriesMode.EXPLICIT)
    sources = CatalogSources(repositories=repositories, groups={}, default_scope=[])

    catalog = await RepositoryCatalog.load(sources, _discovery_providers())

    assert catalog.repositories == []


def test_duplicate_names_are_qualified() -> None:
    sources = CatalogSources(repositories=RepositoriesConfig(), groups={}, default_scope=[])
    repositories = [
        RepositoryRef(name="api", url="u1", provider="github", full_path="org/api"),
        RepositoryRef(name="api", url="u2", provider="gitlab", full_path="grp/api"),
    ]

    catalog = RepositoryCatalog(repositories, sources)

    assert sorted(r.name for r in catalog.repositories) == ["github:org/api", "gitlab:grp/api"]
