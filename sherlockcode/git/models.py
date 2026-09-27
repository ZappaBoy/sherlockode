from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr


class GitCredentials(BaseModel):
    username: str
    password: SecretStr


class CloneRequest(BaseModel):
    url: str
    destination: Path
    credentials: GitCredentials | None = None
    depth: int | None = None


class LogQuery(BaseModel):
    revision: str = "HEAD"
    since: datetime | None = None
    until: datetime | None = None
    author: str | None = None
    paths: list[str] = Field(default_factory=list)
    limit: int = Field(default=200, ge=1)


class GrepQuery(BaseModel):
    pattern: str
    paths: list[str] = Field(default_factory=list)
    ignore_case: bool = False
    fixed_string: bool = False
    revision: str | None = None
    limit: int = Field(default=100, ge=1)


class SearchMatch(BaseModel):
    path: str
    line: int
    text: str
