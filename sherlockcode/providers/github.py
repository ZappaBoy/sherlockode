from typing import Any

import httpx

from sherlockcode.config.models import DiscoveryMode
from sherlockcode.domain.activity import (
    ChangeRequest,
    Contributor,
    Issue,
    Person,
    WorkItemQuery,
    WorkItemState,
)
from sherlockcode.domain.repository import Namespace, RepositoryMetadata, RepositoryRef
from sherlockcode.git.models import GitCredentials
from sherlockcode.providers.base import (
    ChangeRequestSource,
    ContributorSource,
    IssueSource,
    NamespaceSource,
    RepositoryDiscovery,
    RepositoryMetadataSource,
)
from sherlockcode.providers.hosted import HostedProvider, parse_datetime, updated_since


class GitHubProvider(
    HostedProvider,
    RepositoryDiscovery,
    RepositoryMetadataSource,
    ContributorSource,
    ChangeRequestSource,
    IssueSource,
    NamespaceSource,
):
    default_base_url = "https://api.github.com"
    public_git_host = "github.com"

    def _auth_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        return headers | ({"Authorization": f"Bearer {self.token}"} if self.token else {})

    def git_credentials(self) -> GitCredentials | None:
        token = self.config.token
        return GitCredentials(username="x-access-token", password=token) if token else None

    async def discover_repositories(self) -> list[RepositoryRef]:
        if self.config.discovery == DiscoveryMode.ALL:
            items = await self._pages("user/repos", {"affiliation": "owner,collaborator,organization_member"})
        elif self.config.discovery == DiscoveryMode.NAMESPACES:
            items = []
            for namespace in self.config.namespaces:
                items.extend(await self._namespace_repositories(namespace))
        else:
            items = []
        return [self._to_ref(item) for item in items if self.config.include_archived or not item.get("archived")]

    async def _namespace_repositories(self, namespace: str) -> list[dict[str, Any]]:
        try:
            return await self._pages(f"orgs/{namespace}/repos", {"type": "all"})
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 404:
                raise
            return await self._pages(f"users/{namespace}/repos", {"type": "owner"})

    def _to_ref(self, item: dict[str, Any]) -> RepositoryRef:
        return RepositoryRef(
            name=item["name"],
            url=item["clone_url"],
            provider=self.name,
            full_path=item["full_name"],
            default_branch=item.get("default_branch"),
            tags=frozenset(item.get("topics") or []),
        )

    async def repository_metadata(self, repository: RepositoryRef) -> RepositoryMetadata:
        path = self.repository_path(repository)
        data = await self.http.get(f"repos/{path}")
        languages: dict[str, int] = await self.http.get(f"repos/{path}/languages")
        total = sum(languages.values()) or 1
        return RepositoryMetadata(
            repository=repository.name,
            description=data.get("description"),
            default_branch=data.get("default_branch"),
            visibility=data.get("visibility"),
            archived=data.get("archived"),
            primary_language=data.get("language"),
            languages={name: round(100 * size / total, 2) for name, size in languages.items()},
            topics=data.get("topics") or [],
            stars=data.get("stargazers_count"),
            forks=data.get("forks_count"),
            open_issues=data.get("open_issues_count"),
            created_at=parse_datetime(data.get("created_at")),
            updated_at=parse_datetime(data.get("updated_at")),
            last_activity_at=parse_datetime(data.get("pushed_at")),
            web_url=data.get("html_url"),
        )

    async def contributors(self, repository: RepositoryRef) -> list[Contributor]:
        items = await self._pages(f"repos/{self.repository_path(repository)}/contributors", {})
        return [
            Contributor(person=Person(name=item["login"], username=item["login"]), contributions=item["contributions"])
            for item in items
        ]

    async def change_requests(self, repository: RepositoryRef, query: WorkItemQuery) -> list[ChangeRequest]:
        state = "closed" if query.state is WorkItemState.MERGED else query.state.value
        params: dict[str, str | int] = {"state": state, "sort": "updated", "direction": "desc"}
        items = await self._pages(f"repos/{self.repository_path(repository)}/pulls", params, query.limit)
        requests = [_to_change_request(item) for item in updated_since(items, query)]
        if query.state is WorkItemState.MERGED:
            return [request for request in requests if request.state is WorkItemState.MERGED]
        return requests

    async def issues(self, repository: RepositoryRef, query: WorkItemQuery) -> list[Issue]:
        state = "all" if query.state is WorkItemState.MERGED else query.state.value
        params: dict[str, str | int] = {"state": state, "sort": "updated", "direction": "desc"}
        if query.since:
            params["since"] = query.since.isoformat()
        items = await self._pages(f"repos/{self.repository_path(repository)}/issues", params, query.limit)
        return [_to_issue(item) for item in items if "pull_request" not in item]

    async def namespaces(self) -> list[Namespace]:
        if not self.config.namespaces:
            items = await self._pages("user/orgs", {})
        else:
            items = [await self.http.get(f"users/{name}") for name in self.config.namespaces]
        return [
            Namespace(
                name=item["login"],
                full_path=item["login"],
                provider=self.name,
                description=item.get("description") or item.get("bio"),
                web_url=item.get("html_url"),
            )
            for item in items
        ]


def _work_item_fields(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": item["number"],
        "title": item["title"],
        "author": (item.get("user") or {}).get("login"),
        "created_at": parse_datetime(item["created_at"]),
        "updated_at": parse_datetime(item.get("updated_at")),
        "closed_at": parse_datetime(item.get("closed_at")),
        "labels": [label["name"] for label in item.get("labels", [])],
        "web_url": item.get("html_url"),
    }


def _to_change_request(item: dict[str, Any]) -> ChangeRequest:
    merged_at = parse_datetime(item.get("merged_at"))
    state = WorkItemState.MERGED if merged_at else WorkItemState(item["state"])
    return ChangeRequest(
        **_work_item_fields(item),
        state=state,
        merged_at=merged_at,
        source_branch=(item.get("head") or {}).get("ref"),
        target_branch=(item.get("base") or {}).get("ref"),
    )


def _to_issue(item: dict[str, Any]) -> Issue:
    return Issue(**_work_item_fields(item), state=WorkItemState(item["state"]))
