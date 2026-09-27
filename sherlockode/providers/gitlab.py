from typing import Any
from urllib.parse import quote

from sherlockode.config.models import DiscoveryMode
from sherlockode.domain.activity import (
    ChangeRequest,
    Contributor,
    Issue,
    Person,
    WorkItemQuery,
    WorkItemState,
)
from sherlockode.domain.repository import Namespace, RepositoryMetadata, RepositoryRef
from sherlockode.git.models import GitCredentials
from sherlockode.providers.base import (
    ChangeRequestSource,
    ContributorSource,
    IssueSource,
    NamespaceSource,
    RepositoryDiscovery,
    RepositoryMetadataSource,
)
from sherlockode.providers.hosted import HostedProvider, parse_datetime

_STATES = {
    WorkItemState.OPEN: "opened",
    WorkItemState.CLOSED: "closed",
    WorkItemState.MERGED: "merged",
    WorkItemState.ALL: "all",
}


class GitLabProvider(
    HostedProvider,
    RepositoryDiscovery,
    RepositoryMetadataSource,
    ContributorSource,
    ChangeRequestSource,
    IssueSource,
    NamespaceSource,
):
    default_base_url = "https://gitlab.com/api/v4"
    public_git_host = "gitlab.com"

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def git_credentials(self) -> GitCredentials | None:
        token = self.config.token
        return GitCredentials(username="oauth2", password=token) if token else None

    def _project(self, repository: RepositoryRef) -> str:
        return f"projects/{quote(self.repository_path(repository), safe='')}"

    async def discover_repositories(self) -> list[RepositoryRef]:
        items: list[dict[str, Any]] = []
        if self.config.discovery == DiscoveryMode.ALL:
            params: dict[str, str | int] = {"membership": "true"}
            if not self.config.include_archived:
                params["archived"] = "false"
            items = await self._pages("projects", params)
        elif self.config.discovery == DiscoveryMode.NAMESPACES:
            for namespace in self.config.namespaces:
                params = {"include_subgroups": "true", "with_shared": "false"}
                if not self.config.include_archived:
                    params["archived"] = "false"
                items.extend(await self._pages(f"groups/{quote(namespace, safe='')}/projects", params))
        return [self._to_ref(item) for item in items]

    def _to_ref(self, item: dict[str, Any]) -> RepositoryRef:
        return RepositoryRef(
            name=item["path"],
            url=item["http_url_to_repo"],
            provider=self.name,
            full_path=item["path_with_namespace"],
            default_branch=item.get("default_branch"),
            tags=frozenset(item.get("topics") or item.get("tag_list") or []),
        )

    async def repository_metadata(self, repository: RepositoryRef) -> RepositoryMetadata:
        project = self._project(repository)
        data = await self.http.get(project)
        languages: dict[str, float] = await self.http.get(f"{project}/languages")
        return RepositoryMetadata(
            repository=repository.name,
            description=data.get("description"),
            default_branch=data.get("default_branch"),
            visibility=data.get("visibility"),
            archived=data.get("archived"),
            primary_language=max(languages, key=languages.__getitem__) if languages else None,
            languages=languages,
            topics=data.get("topics") or [],
            stars=data.get("star_count"),
            forks=data.get("forks_count"),
            open_issues=data.get("open_issues_count"),
            created_at=parse_datetime(data.get("created_at")),
            updated_at=parse_datetime(data.get("updated_at")),
            last_activity_at=parse_datetime(data.get("last_activity_at")),
            web_url=data.get("web_url"),
        )

    async def contributors(self, repository: RepositoryRef) -> list[Contributor]:
        items = await self._pages(
            f"{self._project(repository)}/repository/contributors", {"order_by": "commits", "sort": "desc"}
        )
        return [
            Contributor(person=Person(name=item["name"], email=item.get("email")), contributions=item["commits"])
            for item in items
        ]

    async def change_requests(self, repository: RepositoryRef, query: WorkItemQuery) -> list[ChangeRequest]:
        items = await self._work_items(f"{self._project(repository)}/merge_requests", query)
        return [
            ChangeRequest(
                **_work_item_fields(item),
                state=_state(item["state"]),
                merged_at=parse_datetime(item.get("merged_at")),
                source_branch=item.get("source_branch"),
                target_branch=item.get("target_branch"),
            )
            for item in items
        ]

    async def issues(self, repository: RepositoryRef, query: WorkItemQuery) -> list[Issue]:
        issue_query = (
            query.model_copy(update={"state": WorkItemState.ALL}) if query.state is WorkItemState.MERGED else query
        )
        items = await self._work_items(f"{self._project(repository)}/issues", issue_query)
        return [Issue(**_work_item_fields(item), state=_state(item["state"])) for item in items]

    async def _work_items(self, path: str, query: WorkItemQuery) -> list[dict[str, Any]]:
        params: dict[str, str | int] = {
            "state": _STATES[query.state],
            "order_by": "updated_at",
            "sort": "desc",
        }
        if query.since:
            params["updated_after"] = query.since.isoformat()
        return await self._pages(path, params, query.limit)

    async def namespaces(self) -> list[Namespace]:
        if self.config.namespaces:
            items = [await self.http.get(f"groups/{quote(name, safe='')}") for name in self.config.namespaces]
        else:
            items = await self._pages("groups", {"min_access_level": 10})
        return [
            Namespace(
                name=item["name"],
                full_path=item["full_path"],
                provider=self.name,
                description=item.get("description"),
                web_url=item.get("web_url"),
            )
            for item in items
        ]


def _state(value: str) -> WorkItemState:
    return {"opened": WorkItemState.OPEN, "locked": WorkItemState.OPEN}.get(value) or WorkItemState(value)


def _work_item_fields(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": item["iid"],
        "title": item["title"],
        "author": (item.get("author") or {}).get("username"),
        "created_at": parse_datetime(item["created_at"]),
        "updated_at": parse_datetime(item.get("updated_at")),
        "closed_at": parse_datetime(item.get("closed_at")),
        "labels": item.get("labels", []),
        "web_url": item.get("web_url"),
    }
