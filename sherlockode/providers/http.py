from typing import Any

import httpx

from sherlockode.providers.base import ApiRequest, ApiResponse


# Read-only JSON client following RFC 5988 `Link: rel="next"` pagination (GitHub and GitLab).
class ProviderHttpClient:
    def __init__(self, client: httpx.AsyncClient, page_size_param: str = "per_page") -> None:
        self._client = client
        self._page_size_param = page_size_param

    async def get(self, path: str, params: dict[str, str | int] | None = None) -> Any:
        return (await self._get(path, params)).json()

    async def get_pages(self, request: ApiRequest) -> list[Any]:
        response = await self.api_get(request)
        return response.data if isinstance(response.data, list) else [response.data]

    async def api_get(self, request: ApiRequest) -> ApiResponse:
        params = {self._page_size_param: min(100, request.max_items), **request.params}
        response = await self._get(request.path, params)
        data = response.json()
        if not isinstance(data, list):
            return ApiResponse(endpoint=request.path, status_code=response.status_code, data=data)
        next_url = response.links.get("next", {}).get("url")
        while next_url and len(data) < request.max_items:
            page = await self._get(next_url)
            data.extend(page.json())
            next_url = page.links.get("next", {}).get("url")
        return ApiResponse(
            endpoint=request.path,
            status_code=response.status_code,
            data=data[: request.max_items],
            truncated=bool(next_url) or len(data) > request.max_items,
        )

    async def _get(self, url: str, params: dict[str, str | int] | None = None) -> httpx.Response:
        response = await self._client.get(url, params=params)
        response.raise_for_status()
        return response

    async def aclose(self) -> None:
        await self._client.aclose()


def build_http_client(base_url: str, headers: dict[str, str], timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url,
        headers={"User-Agent": "sherlockode", **headers},
        timeout=timeout,
        follow_redirects=True,
    )
