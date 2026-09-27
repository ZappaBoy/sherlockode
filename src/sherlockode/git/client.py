import base64
import fnmatch
import os
from datetime import datetime
from pathlib import Path

from sherlockode.domain.activity import Commit, Contributor, GitRef, Person, RefKind
from sherlockode.git.models import CloneRequest, GitCredentials, GrepQuery, LogQuery, SearchMatch
from sherlockode.process import CommandResult, CommandSpec, run_checked, run_command

FIELD_SEPARATOR = "\x1f"
RECORD_SEPARATOR = "\x1e"
_LOG_FORMAT = FIELD_SEPARATOR.join(["%H", "%an", "%ae", "%aI", "%cI", "%s"]) + RECORD_SEPARATOR
_REF_FORMAT = FIELD_SEPARATOR.join(["%(refname:short)", "%(objectname)", "%(creatordate:iso-strict)"])

_HARDENING = {
    "core.hooksPath": "/dev/null",
    "core.fsmonitor": "false",
    "protocol.ext.allow": "never",
    "protocol.file.allow": "user",
    "submodule.recurse": "false",
    "credential.helper": "",
}


class GitClient:
    """Thin async wrapper over the git CLI. Never executes repository-provided hooks or helpers."""

    def __init__(self, timeout_seconds: float = 600, max_output_bytes: int = 20_000_000) -> None:
        self._timeout = timeout_seconds
        self._max_output = max_output_bytes

    async def clone(self, request: CloneRequest) -> None:
        request.destination.parent.mkdir(parents=True, exist_ok=True)
        argv = ["clone", "--no-recurse-submodules", "--quiet"]
        if request.depth:
            argv += ["--depth", str(request.depth), "--no-single-branch"]
        argv += ["--", request.url, str(request.destination)]
        await self._run(argv, credentials=request.credentials)

    async def fetch(self, checkout: Path, credentials: GitCredentials | None = None) -> None:
        await self._run(["fetch", "--prune", "--tags", "--quiet", "origin"], checkout, credentials)
        await self._run(["reset", "--hard", "--quiet", "@{upstream}"], checkout, check=False)

    async def checkout(self, checkout: Path, revision: str) -> None:
        await self._run(["checkout", "--quiet", "--detach", revision], checkout)

    async def head(self, checkout: Path, revision: str = "HEAD") -> str:
        return (await self._run(["rev-parse", "--verify", f"{revision}^{{commit}}"], checkout)).stdout.strip()

    async def log(self, checkout: Path, query: LogQuery) -> list[Commit]:
        argv = ["log", f"--format={_LOG_FORMAT}", f"--max-count={query.limit}", "--no-merges"]
        if query.since:
            argv.append(f"--since={query.since.isoformat()}")
        if query.until:
            argv.append(f"--until={query.until.isoformat()}")
        if query.author:
            argv.append(f"--author={query.author}")
        argv += [query.revision, "--", *query.paths]
        result = await self._run(argv, checkout)
        return [_parse_commit(record) for record in result.stdout.split(RECORD_SEPARATOR) if record.strip()]

    async def contributors(self, checkout: Path, revision: str = "HEAD") -> list[Contributor]:
        result = await self._run(["shortlog", "--summary", "--numbered", "--email", revision], checkout)
        return [_parse_shortlog(line) for line in result.stdout.splitlines() if line.strip()]

    async def refs(self, checkout: Path, kind: RefKind) -> list[GitRef]:
        namespace = "refs/tags" if kind is RefKind.TAG else "refs/remotes/origin"
        result = await self._run(
            ["for-each-ref", "--sort=-creatordate", f"--format={_REF_FORMAT}", namespace], checkout
        )
        refs = [_parse_ref(line, kind) for line in result.stdout.splitlines() if line.strip()]
        return [ref for ref in refs if not ref.name.endswith("/HEAD") and ref.name != "origin"]

    async def list_files(self, checkout: Path, pattern: str | None = None) -> list[str]:
        files = (await self._run(["ls-files", "-z"], checkout)).stdout.split("\0")
        return [f for f in files if f and (pattern is None or _matches_path(f, pattern))]

    async def grep(self, checkout: Path, query: GrepQuery) -> list[SearchMatch]:
        argv = ["grep", "-n", "-I", "--no-color", "--full-name", "-z"]
        argv += ["-F"] if query.fixed_string else ["-E"]
        if query.ignore_case:
            argv.append("-i")
        argv += ["-e", query.pattern]
        if query.revision:
            argv.append(query.revision)
        argv += ["--", *query.paths]
        result = await self._run(argv, checkout, check=False)
        if result.exit_code not in (0, 1):
            raise ValueError(result.stderr.strip() or "git grep failed")
        matches = [_parse_grep(line, query.revision) for line in result.stdout.splitlines() if line]
        return matches[: query.limit]

    async def show_file(self, checkout: Path, path: str, revision: str) -> str:
        return (await self._run(["show", f"{revision}:{path}"], checkout)).stdout

    async def _run(
        self,
        argv: list[str],
        cwd: Path | None = None,
        credentials: GitCredentials | None = None,
        *,
        check: bool = True,
    ) -> CommandResult:
        spec = CommandSpec(
            argv=["git", *argv],
            cwd=cwd,
            env=_git_environment(credentials),
            timeout_seconds=self._timeout,
            max_output_bytes=self._max_output,
        )
        return await (run_checked(spec) if check else run_command(spec))


def _git_environment(credentials: GitCredentials | None) -> dict[str, str]:
    config = dict(_HARDENING)
    if credentials:
        token = f"{credentials.username}:{credentials.password.get_secret_value()}"
        config["http.extraHeader"] = f"Authorization: Basic {base64.b64encode(token.encode()).decode()}"
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment |= {"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_COUNT": str(len(config)), "LC_ALL": "C"}
    for index, (key, value) in enumerate(config.items()):
        environment[f"GIT_CONFIG_KEY_{index}"] = key
        environment[f"GIT_CONFIG_VALUE_{index}"] = value
    return environment


def _matches_path(path: str, pattern: str) -> bool:
    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path.rsplit("/", 1)[-1], pattern)


def _parse_commit(record: str) -> Commit:
    sha, name, email, authored, committed, subject = record.strip("\n").split(FIELD_SEPARATOR, 5)
    return Commit(
        sha=sha,
        author=Person(name=name, email=email or None),
        authored_at=datetime.fromisoformat(authored),
        committed_at=datetime.fromisoformat(committed),
        subject=subject,
    )


def _parse_shortlog(line: str) -> Contributor:
    count, identity = line.strip().split("\t", 1)
    name, _, email = identity.partition(" <")
    return Contributor(person=Person(name=name, email=email.rstrip(">") or None), contributions=int(count))


def _parse_ref(line: str, kind: RefKind) -> GitRef:
    name, sha, date = line.split(FIELD_SEPARATOR)
    return GitRef(
        name=name.removeprefix("origin/"),
        kind=kind,
        sha=sha,
        updated_at=datetime.fromisoformat(date) if date else None,
    )


def _parse_grep(line: str, revision: str | None) -> SearchMatch:
    path, number, text = line.split("\0", 2)
    if revision:
        path = path.removeprefix(f"{revision}:")
    return SearchMatch(path=path, line=int(number), text=text.strip()[:500])
