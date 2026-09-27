from abc import abstractmethod
from datetime import datetime
from typing import Any

from sherlockode.domain.activity import WorkItemQuery
from sherlockode.providers.base import (
    ApiRequest,
    ApiResponse,
    Provider,
    ProviderContext,
    RawApiAccess,
    host_of,
)
from sherlockode.providers.http import ProviderHttpClient, build_http_client


# Base for providers exposing a paginated REST API.
class HostedProvider(Provider, RawApiAccess):
    default_base_url: str
    public_git_host: str
    page_size_param = "per_page"

    def __init__(self, context: ProviderContext) -> None:
        super().__init__(context)
        client = build_http_client(self.base_url, self._auth_headers(), self.config.timeout_seconds)
        self.http = ProviderHttpClient(client, self.page_size_param)

    @property
    def base_url(self) -> str:
        return (self.config.base_url or self.default_base_url).rstrip("/") + "/"

    @property
    def token(self) -> str | None:
        return self.config.token.get_secret_value() if self.config.token else None

    def owns(self, url: str) -> bool:
        return host_of(url) in (self.config.hosts or [self._default_git_host()])

    def _default_git_host(self) -> str:
        return host_of(self.config.base_url) if self.config.base_url else self.public_git_host

    @abstractmethod
    def _auth_headers(self) -> dict[str, str]: ...

    async def api_get(self, request: ApiRequest) -> ApiResponse:
        return await self.http.api_get(request)

    async def _pages(self, path: str, params: dict[str, str | int], limit: int = 1000) -> list[Any]:
        return await self.http.get_pages(ApiRequest(path=path, params=params, max_items=limit))

    async def aclose(self) -> None:
        await self.http.aclose()


def parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def updated_since(items: list[dict[str, Any]], query: WorkItemQuery) -> list[dict[str, Any]]:
    if query.since is None:
        return items
    since = query.since
    return [item for item in items if (parse_datetime(item.get("updated_at")) or since) >= since]
