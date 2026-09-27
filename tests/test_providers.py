import json
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import ValidationError
from pydantic_ai import PrefixedToolset

from sherlockode.config.models import ProviderConfig
from sherlockode.domain.activity import WorkItemQuery, WorkItemState
from sherlockode.domain.repository import RepositoryRef
from sherlockode.providers import ApiRequest, ProviderCapability, ProviderContext
from sherlockode.providers.github import GitHubProvider
from sherlockode.providers.gitlab import GitLabProvider
from sherlockode.providers.hosted import HostedProvider
from sherlockode.providers.http import ProviderHttpClient
from sherlockode.providers.mcp import build_mcp_toolset, uses_mcp, uses_native_tools

Handler = Callable[[httpx.Request], httpx.Response]


def _with_transport[P: HostedProvider](provider: P, handler: Handler) -> P:
    client = httpx.AsyncClient(
        base_url=provider.base_url, headers=provider._auth_headers(), transport=httpx.MockTransport(handler)
    )
    provider.http = ProviderHttpClient(client)
    return provider


def _json(data: object, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        200, content=json.dumps(data), headers={"content-type": "application/json", **(headers or {})}
    )


def _github(handler: Handler, namespaces: list[str] | None = None) -> GitHubProvider:
    config = ProviderConfig(kind="github", token="t", namespaces=namespaces or [])
    return _with_transport(GitHubProvider(ProviderContext(name="github", config=config)), handler)


def _gitlab(handler: Handler, namespaces: list[str] | None = None) -> GitLabProvider:
    config = ProviderConfig(kind="gitlab", base_url="https://gitlab.example.com/api/v4", namespaces=namespaces or [])
    return _with_transport(GitLabProvider(ProviderContext(name="gitlab", config=config)), handler)


def _pull(number: int, merged: bool) -> dict[str, object]:
    return {
        "number": number,
        "title": f"PR {number}",
        "state": "closed",
        "user": {"login": "alice"},
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "merged_at": "2026-01-02T00:00:00Z" if merged else None,
        "labels": [],
        "head": {"ref": "feature"},
        "base": {"ref": "main"},
    }


async def test_github_discovery_follows_pagination_and_skips_archived() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer t"
        page = request.url.params.get("page", "1")
        repo = {"name": f"r{page}", "clone_url": f"https://github.com/o/r{page}.git", "full_name": f"o/r{page}"}
        if page == "1":
            return _json([repo], {"Link": '<https://api.github.com/orgs/o/repos?page=2>; rel="next"'})
        return _json([repo, {**repo, "name": "old", "archived": True}])

    repositories = await _github(handler, ["o"]).discover_repositories()

    assert [(r.name, r.full_path) for r in repositories] == [("r1", "o/r1"), ("r2", "o/r2")]


async def test_github_merged_change_requests() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/o/r/pulls"
        assert request.url.params["state"] == "closed"
        return _json([_pull(1, merged=True), _pull(2, merged=False)])

    repository = RepositoryRef(name="r", url="https://github.com/o/r.git", provider="github")
    query = WorkItemQuery(repository="r", state=WorkItemState.MERGED)

    requests = await _github(handler).change_requests(repository, query)

    assert [(r.number, r.state, r.target_branch) for r in requests] == [(1, WorkItemState.MERGED, "main")]


async def test_gitlab_merge_requests_use_encoded_project_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.raw_path.startswith(b"/api/v4/projects/platform%2Fsvc/merge_requests")
        assert request.url.params["updated_after"].startswith("2026-01-01")
        return _json(
            [
                {
                    "iid": 7,
                    "title": "MR",
                    "state": "opened",
                    "author": {"username": "bob"},
                    "created_at": "2026-01-03T00:00:00Z",
                    "labels": ["x"],
                    "source_branch": "f",
                    "target_branch": "main",
                }
            ]
        )

    repository = RepositoryRef(name="svc", url="git@gitlab.example.com:platform/svc.git", provider="gitlab")
    query = WorkItemQuery(repository="svc", since=datetime(2026, 1, 1, tzinfo=UTC))

    requests = await _gitlab(handler).change_requests(repository, query)

    assert [(r.number, r.state, r.author) for r in requests] == [(7, WorkItemState.OPEN, "bob")]


def test_gitlab_routes_self_hosted_urls_and_supplies_clone_credentials() -> None:
    config = ProviderConfig(kind="gitlab", base_url="https://gitlab.example.com/api/v4", token="secret")
    provider = GitLabProvider(ProviderContext(name="gitlab", config=config))

    assert provider.owns("git@gitlab.example.com:platform/svc.git")
    assert not provider.owns("https://github.com/o/r.git")
    credentials = provider.git_credentials()
    assert credentials is not None and credentials.username == "oauth2"
    assert ProviderCapability.CHANGE_REQUESTS in provider.capabilities


@pytest.mark.parametrize("path", ["https://evil.example.com/x", "//evil.example.com/x", "repos/../../x"])
def test_raw_api_paths_stay_on_provider(path: str) -> None:
    with pytest.raises(ValidationError):
        ApiRequest(path=path)


async def test_raw_api_get_returns_objects_and_truncates_lists() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/rate_limit"):
            return _json({"remaining": 5})
        return _json([{"n": i} for i in range(5)], {"Link": '<https://api.github.com/x?page=2>; rel="next"'})

    provider = _github(handler)

    single = await provider.api_get(ApiRequest(path="/rate_limit"))
    listing = await provider.api_get(ApiRequest(path="repos/o/r/releases", max_items=3))

    assert single.data == {"remaining": 5}
    assert len(listing.data) == 3 and listing.truncated


def test_mcp_toolset_is_namespaced_and_filtered() -> None:
    config = ProviderConfig(
        kind="github",
        token="t",
        integration="mcp",
        mcp={"transport": "stdio", "command": "github-mcp-server", "token_env": "GITHUB_TOKEN", "allowed_tools": ["x"]},
    )
    provider = GitHubProvider(ProviderContext(name="github", config=config))

    toolset = build_mcp_toolset(provider)

    assert isinstance(toolset, PrefixedToolset) and toolset.prefix == "github_mcp"
    assert uses_mcp(provider) and not uses_native_tools(provider)
