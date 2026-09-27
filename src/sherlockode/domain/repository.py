from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RepositoryRef(BaseModel):
    """Provider-independent identity of a repository known to the catalog."""

    model_config = ConfigDict(frozen=True)

    name: str
    url: str
    provider: str
    full_path: str | None = None
    default_branch: str | None = None
    tags: frozenset[str] = frozenset()

    @property
    def namespace(self) -> str | None:
        if not self.full_path or "/" not in self.full_path:
            return None
        return self.full_path.rsplit("/", 1)[0]


class RepositoryMetadata(BaseModel):
    repository: str
    description: str | None = None
    default_branch: str | None = None
    visibility: str | None = None
    archived: bool | None = None
    primary_language: str | None = None
    languages: dict[str, float] = Field(default_factory=dict)
    topics: list[str] = Field(default_factory=list)
    stars: int | None = None
    forks: int | None = None
    open_issues: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_activity_at: datetime | None = None
    web_url: str | None = None


class Namespace(BaseModel):
    """A provider-level container of repositories: a GitHub organization or a GitLab group."""

    name: str
    full_path: str
    provider: str
    description: str | None = None
    web_url: str | None = None
