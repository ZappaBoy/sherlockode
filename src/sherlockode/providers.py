from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from .models import ProviderKind, RepositoryDefinition


class RepositoryQuery(BaseModel):
    group: str | None = None
    languages: list[str] = Field(default_factory=list)


class ContributorQuery(BaseModel):
    repository: str
    group: str | None = None


class ProviderAdapter(ABC):
    @property
    @abstractmethod
    def kind(self) -> ProviderKind:
        raise NotImplementedError

    @abstractmethod
    def list_repositories(self, query: RepositoryQuery) -> list[RepositoryDefinition]:
        raise NotImplementedError

    @abstractmethod
    def get_contributors(self, query: ContributorQuery) -> list[str]:
        raise NotImplementedError


class ProviderRegistry(BaseModel):
    adapters: dict[ProviderKind, ProviderAdapter] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}

    def register(self, adapter: ProviderAdapter) -> None:
        self.adapters[adapter.kind] = adapter

    def get(self, provider: ProviderKind) -> ProviderAdapter:
        if provider not in self.adapters:
            raise KeyError(f"provider not registered: {provider}")
        return self.adapters[provider]
