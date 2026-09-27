from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from sherlockode.agent.deps import InvestigationDeps, Observation, RepositoryResult, per_repository
from sherlockode.domain.activity import Commit, Contributor, GitRef, RefKind
from sherlockode.domain.evidence import EvidenceDraft, EvidenceKind, EvidenceSource, SourceKind
from sherlockode.domain.repository import RepositoryRef
from sherlockode.git.models import GrepQuery, LogQuery, SearchMatch

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class CodeSearch(BaseModel):
    pattern: str = Field(description="Extended regular expression, or a literal string when fixed_string is set.")
    repositories: list[str] = Field(default_factory=list, description="Groups or repositories; empty for all.")
    paths: list[str] = Field(default_factory=list, description="Git pathspecs, e.g. '*.py' or 'src/'.")
    ignore_case: bool = False
    fixed_string: bool = False
    max_results_per_repository: int = Field(default=50, ge=1)


class FileReadRequest(BaseModel):
    repository: str
    path: str
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    revision: str | None = Field(default=None, description="Commit, branch or tag; defaults to the checkout.")


class FileContent(BaseModel):
    path: str
    commit: str
    total_lines: int
    content: str = Field(description="Requested lines, each prefixed with its line number.")


class ActivityRequest(BaseModel):
    repositories: list[str] = Field(default_factory=list, description="Groups or repositories; empty for all.")
    since: datetime | None = None
    until: datetime | None = None
    timezone: str | None = Field(
        default=None,
        description="IANA zone to bucket in, e.g. 'Europe/Rome'. Default: each author's local time.",
    )


class ActivityHistogram(BaseModel):
    commits: int
    by_hour: dict[int, int]
    by_weekday: dict[str, int]


def build_git_toolset() -> FunctionToolset[InvestigationDeps]:  # noqa: PLR0915
    toolset = FunctionToolset[InvestigationDeps]()

    @toolset.tool(
        description="Clone or update repositories locally and return the checked-out commit. "
        "Other git tools do this lazily."
    )
    async def sync_repositories(
        ctx: RunContext[InvestigationDeps],
        repositories: Annotated[list[str], Field(description="Groups or repositories; empty for the whole scope.")],
    ) -> list[RepositoryResult[str]]:
        async def sync(repository: RepositoryRef) -> Observation[str]:
            commit = await ctx.deps.git.head(await ctx.deps.checkouts.ensure(repository))
            return ctx.deps.observe(commit, _git_evidence(repository, f"checked out at {commit}", "git fetch"))

        return await per_repository(ctx.deps.repositories(repositories), sync)

    @toolset.tool(description="Read commit history (merge commits excluded), newest first.")
    async def git_log(
        ctx: RunContext[InvestigationDeps], repository: str, query: LogQuery
    ) -> Observation[list[Commit]]:
        ref = ctx.deps.repository(repository)
        checkout = await ctx.deps.checkouts.ensure(ref)
        bounded = query.model_copy(update={"limit": min(query.limit, ctx.deps.settings.limits.max_log_entries)})
        commits = await ctx.deps.git.log(checkout, bounded)
        command = f"git log {bounded.model_dump_json(exclude_defaults=True)}"
        return ctx.deps.observe(commits, _git_evidence(ref, f"{len(commits)} commits returned", command))

    @toolset.tool(description="Commit counts per author from git history (git shortlog), for each repository.")
    async def git_contributors(
        ctx: RunContext[InvestigationDeps],
        repositories: Annotated[list[str], Field(description="Groups or repositories; empty for the whole scope.")],
    ) -> list[RepositoryResult[list[Contributor]]]:
        async def contributors(repository: RepositoryRef) -> Observation[list[Contributor]]:
            checkout = await ctx.deps.checkouts.ensure(repository)
            found = (await ctx.deps.git.contributors(checkout))[:100]
            return ctx.deps.observe(found, _git_evidence(repository, f"{len(found)} authors", "git shortlog -sne HEAD"))

        return await per_repository(ctx.deps.repositories(repositories), contributors)

    @toolset.tool(description="List remote branches or tags with their latest commit date, most recent first.")
    async def git_refs(ctx: RunContext[InvestigationDeps], repository: str, kind: RefKind) -> Observation[list[GitRef]]:
        ref = ctx.deps.repository(repository)
        refs = await ctx.deps.git.refs(await ctx.deps.checkouts.ensure(ref), kind)
        return ctx.deps.observe(
            refs, _git_evidence(ref, f"{len(refs)} {kind.value} refs", f"git for-each-ref ({kind})")
        )

    @toolset.tool(
        description="List tracked files, optionally filtered by a glob matched against the path or file name."
    )
    async def list_files(
        ctx: RunContext[InvestigationDeps],
        repository: Annotated[str, Field(description="Repository name.")],
        pattern: Annotated[
            str | None, Field(description="Glob such as '*.py', 'Dockerfile*' or '.github/workflows/*'.")
        ] = None,
    ) -> Observation[list[str]]:
        ref = ctx.deps.repository(repository)
        files = await ctx.deps.git.list_files(await ctx.deps.checkouts.ensure(ref), pattern)
        limit = ctx.deps.settings.limits.max_search_results
        statement = f"{len(files)} tracked files match {pattern or '*'}"
        return ctx.deps.observe(files[:limit], _git_evidence(ref, statement, f"git ls-files {pattern or ''}".strip()))

    @toolset.tool(
        description="Search tracked file contents across repositories (git grep). "
        "Repositories without matches are omitted."
    )
    async def search_code(
        ctx: RunContext[InvestigationDeps], search: CodeSearch
    ) -> list[RepositoryResult[list[SearchMatch]]]:
        limit = min(search.max_results_per_repository, ctx.deps.settings.limits.max_search_results)
        query = GrepQuery(
            pattern=search.pattern,
            paths=search.paths,
            ignore_case=search.ignore_case,
            fixed_string=search.fixed_string,
            limit=limit,
        )

        async def grep(repository: RepositoryRef) -> Observation[list[SearchMatch]]:
            try:
                matches = await ctx.deps.git.grep(await ctx.deps.checkouts.ensure(repository), query)
            except ValueError as error:
                raise ModelRetry(f"invalid search: {error}") from None
            statement = f"{len(matches)} matches for /{search.pattern}/"
            return ctx.deps.observe(matches, _git_evidence(repository, statement, f"git grep -E {search.pattern!r}"))

        results = await per_repository(ctx.deps.repositories(search.repositories), grep)
        return [result for result in results if result.error or result.data]

    @toolset.tool(description="Read a line range of a tracked file, at the checkout or at a given revision.")
    async def read_file(ctx: RunContext[InvestigationDeps], request: FileReadRequest) -> Observation[FileContent]:
        ref = ctx.deps.repository(request.repository)
        checkout = await ctx.deps.checkouts.ensure(ref)
        commit = await ctx.deps.git.head(checkout, request.revision or "HEAD")
        text = await _read(ctx.deps, checkout, request)
        lines = text.splitlines()
        end = min(request.end_line or len(lines), len(lines), request.start_line + 1999)
        numbered = "\n".join(f"{n}: {lines[n - 1]}" for n in range(request.start_line, end + 1))
        content = FileContent(path=request.path, commit=commit, total_lines=len(lines), content=numbered)
        source = EvidenceSource(
            kind=SourceKind.FILE,
            repository=ref.name,
            path=request.path,
            line=request.start_line,
            commit=commit,
        )
        draft = EvidenceDraft(
            kind=EvidenceKind.OBSERVED, statement=f"read lines {request.start_line}-{end}", source=source
        )
        return ctx.deps.observe(content, draft)

    @toolset.tool(description="Histogram of commit author times by hour of day (0-23) and weekday, per repository.")
    async def commit_activity(
        ctx: RunContext[InvestigationDeps], request: ActivityRequest
    ) -> list[RepositoryResult[ActivityHistogram]]:
        zone = _zone(request.timezone)
        limit = ctx.deps.settings.limits.max_log_entries * 10
        query = LogQuery(since=request.since, until=request.until, limit=limit)

        async def activity(repository: RepositoryRef) -> Observation[ActivityHistogram]:
            commits = await ctx.deps.git.log(await ctx.deps.checkouts.ensure(repository), query)
            histogram = _histogram(commits, zone)
            draft = EvidenceDraft(
                kind=EvidenceKind.COMPUTED,
                statement=f"commit time distribution over {histogram.commits} commits: {histogram.by_hour}",
                source=EvidenceSource(
                    kind=SourceKind.GIT,
                    repository=repository.name,
                    command=f"git log --no-merges {query.model_dump_json(exclude_defaults=True)} | histogram",
                ),
            )
            return ctx.deps.observe(histogram, draft)

        return await per_repository(ctx.deps.repositories(request.repositories), activity)

    return toolset


async def _read(deps: InvestigationDeps, checkout: Path, request: FileReadRequest) -> str:
    if request.revision:
        return await deps.git.show_file(checkout, request.path, request.revision)
    file = (checkout / request.path).resolve()
    if not file.is_relative_to(checkout.resolve()) or not file.is_file():
        raise ModelRetry(f"'{request.path}' is not a file in the repository. Use list_files to find paths.")
    if file.stat().st_size > deps.settings.limits.max_file_bytes:
        raise ModelRetry(f"'{request.path}' is too large to read; use search_code to locate the relevant lines.")
    return file.read_text(encoding="utf-8", errors="replace")


def _git_evidence(repository: RepositoryRef, statement: str, command: str) -> EvidenceDraft:
    return EvidenceDraft(
        kind=EvidenceKind.OBSERVED,
        statement=f"{repository.name}: {statement}",
        source=EvidenceSource(kind=SourceKind.GIT, repository=repository.name, command=command),
    )


def _zone(name: str | None) -> ZoneInfo | None:
    try:
        return ZoneInfo(name) if name else None
    except (KeyError, ValueError):
        raise ModelRetry(f"unknown timezone '{name}'") from None


def _histogram(commits: list[Commit], zone: ZoneInfo | None) -> ActivityHistogram:
    times = [commit.authored_at.astimezone(zone) if zone else commit.authored_at for commit in commits]
    hours = Counter(time.hour for time in times)
    weekdays = Counter(_WEEKDAYS[time.weekday()] for time in times)
    return ActivityHistogram(
        commits=len(commits),
        by_hour={hour: hours[hour] for hour in range(24)},
        by_weekday={day: weekdays[day] for day in _WEEKDAYS},
    )
