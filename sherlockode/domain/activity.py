from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Person(BaseModel):
    name: str
    email: str | None = None
    username: str | None = None


class Commit(BaseModel):
    sha: str
    author: Person
    authored_at: datetime
    committed_at: datetime
    subject: str


class Contributor(BaseModel):
    person: Person
    contributions: int


class RefKind(StrEnum):
    BRANCH = "branch"
    TAG = "tag"


class GitRef(BaseModel):
    name: str
    kind: RefKind
    sha: str
    updated_at: datetime | None = None


class WorkItemState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    MERGED = "merged"
    ALL = "all"


# Common shape of issues and pull/merge requests across providers.
class WorkItem(BaseModel):
    number: int
    title: str
    state: WorkItemState
    author: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    closed_at: datetime | None = None
    merged_at: datetime | None = None
    labels: list[str] = Field(default_factory=list)
    web_url: str | None = None


class ChangeRequest(WorkItem):
    source_branch: str | None = None
    target_branch: str | None = None


class Issue(WorkItem):
    pass


class WorkItemQuery(BaseModel):
    repository: str
    state: WorkItemState = WorkItemState.ALL
    since: datetime | None = None
    limit: int = Field(default=100, ge=1, le=1000)
