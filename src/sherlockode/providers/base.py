from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from sherlockode.config.models import ProviderConfig
from sherlockode.domain.activity import ChangeRequest, Contributor, Issue, WorkItemQuery
from sherlockode.domain.repository import Namespace, RepositoryMetadata, RepositoryRef
from sherlockode.git.models import GitCredentials


class ProviderCapability(StrEnum):
    DISCOVERY = "discovery"
    METADATA = "metadata"
    CONTRIBUTORS = "contributors"
    CHANGE_REQUESTS = "change_requests"
    ISSUES = "issues"
    NAMESPACES = "namespaces"
    RAW_API = "raw_api"


class ProviderContext(BaseModel):
    name: str
    config: ProviderConfig


class Provider:
    """A Git hosting integration. Optional capabilities are added through the mixins below."""

    def __init__(self, context: ProviderContext) -> None:
        self.name = context.name
        self.config = context.config

    @property
    def kind(self) -> str:
        return self.config.kind

    @property
    def capabilities(self) -> frozenset[ProviderCapability]:
        return frozenset(capability for capability, mixin in _CAPABILITY_MIXINS.items() if isinstance(self, mixin))

    def supports(self, capability: ProviderCapability) -> bool:
        return capability in self.capabilities

    def owns(self, url: str) -> bool:
        return bool(self.config.hosts) and host_of(url) in self.config.hosts

    def git_credentials(self) -> GitCredentials | None:
        return None

    def repository_path(self, repository: RepositoryRef) -> str:
        if repository.full_path:
            return repository.full_path
        path = urlparse(_normalize_scp_url(repository.url)).path.strip("/")
        return path.removesuffix(".git")

    async def aclose(self) -> None:
        return None


class RepositoryDiscovery(ABC):
    @abstractmethod
    async def discover_repositories(self) -> list[RepositoryRef]: ...


class RepositoryMetadataSource(ABC):
    @abstractmethod
    async def repository_metadata(self, repository: RepositoryRef) -> RepositoryMetadata: ...


class ContributorSource(ABC):
    @abstractmethod
    async def contributors(self, repository: RepositoryRef) -> list[Contributor]: ...


class ChangeRequestSource(ABC):
    @abstractmethod
    async def change_requests(self, repository: RepositoryRef, query: WorkItemQuery) -> list[ChangeRequest]: ...


class IssueSource(ABC):
    @abstractmethod
    async def issues(self, repository: RepositoryRef, query: WorkItemQuery) -> list[Issue]: ...


class NamespaceSource(ABC):
    @abstractmethod
    async def namespaces(self) -> list[Namespace]: ...


class ApiRequest(BaseModel):
    path: str
    params: dict[str, str | int] = Field(default_factory=dict)
    max_items: int = Field(default=100, ge=1, le=1000)

    @field_validator("path")
    @classmethod
    def _relative_to_provider(cls, path: str) -> str:
        if "://" in path or path.startswith("//") or ".." in path.split("/"):
            raise ValueError("path must be relative to the provider API base URL")
        return path.lstrip("/")


class ApiResponse(BaseModel):
    endpoint: str
    status_code: int
    data: Any
    truncated: bool = False


class RawApiAccess(ABC):
    """Read-only access to provider endpoints not covered by the typed capabilities."""

    @abstractmethod
    async def api_get(self, request: ApiRequest) -> ApiResponse: ...


_CAPABILITY_MIXINS: dict[ProviderCapability, type] = {
    ProviderCapability.DISCOVERY: RepositoryDiscovery,
    ProviderCapability.METADATA: RepositoryMetadataSource,
    ProviderCapability.CONTRIBUTORS: ContributorSource,
    ProviderCapability.CHANGE_REQUESTS: ChangeRequestSource,
    ProviderCapability.ISSUES: IssueSource,
    ProviderCapability.NAMESPACES: NamespaceSource,
    ProviderCapability.RAW_API: RawApiAccess,
}


def _normalize_scp_url(url: str) -> str:
    if "://" not in url and ":" in url:
        host, path = url.split(":", 1)
        return f"ssh://{host}/{path}"
    return url


def host_of(url: str) -> str:
    return (urlparse(_normalize_scp_url(url)).hostname or "").lower()


def repository_name_from_url(url: str) -> str:
    return urlparse(_normalize_scp_url(url)).path.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
