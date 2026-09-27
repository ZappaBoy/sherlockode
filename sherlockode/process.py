import asyncio
import contextlib
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class CommandSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    argv: Sequence[str]
    cwd: Path | None = None
    env: Mapping[str, str] | None = None
    timeout_seconds: float = 120
    max_output_bytes: int = 1_000_000
    stdin: bytes | None = None


class CommandResult(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class CommandFailedError(RuntimeError):
    def __init__(self, spec: CommandSpec, result: CommandResult) -> None:
        reason = "timed out" if result.timed_out else f"exited with {result.exit_code}"
        super().__init__(f"{spec.argv[0]} {reason}: {result.stderr.strip()[:2000]}")
        self.result = result


class _Captured(BaseModel):
    text: str = ""
    truncated: bool = False
    chunks: list[bytes] = Field(default_factory=list, exclude=True)


async def _drain(stream: asyncio.StreamReader, limit: int) -> _Captured:
    captured = _Captured()
    size = 0
    while chunk := await stream.read(65536):
        if size < limit:
            captured.chunks.append(chunk[: limit - size])
        size += len(chunk)
    captured.truncated = size > limit
    captured.text = b"".join(captured.chunks).decode("utf-8", errors="replace")
    return captured


async def run_command(spec: CommandSpec) -> CommandResult:
    started = time.monotonic()
    process = await asyncio.create_subprocess_exec(
        *spec.argv,
        cwd=spec.cwd,
        env=dict(spec.env) if spec.env is not None else None,
        stdin=asyncio.subprocess.PIPE if spec.stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    assert process.stdout is not None and process.stderr is not None
    if spec.stdin is not None and process.stdin is not None:
        process.stdin.write(spec.stdin)
        await process.stdin.drain()
        process.stdin.close()
    readers = asyncio.gather(
        _drain(process.stdout, spec.max_output_bytes), _drain(process.stderr, spec.max_output_bytes)
    )
    timed_out = False
    try:
        stdout, stderr = await asyncio.wait_for(readers, timeout=spec.timeout_seconds)
        await process.wait()
    except TimeoutError:
        timed_out = True
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()
        stdout, stderr = _Captured(), _Captured(text=f"timed out after {spec.timeout_seconds}s")
    return CommandResult(
        exit_code=process.returncode if process.returncode is not None else -1,
        stdout=stdout.text,
        stderr=stderr.text,
        duration_seconds=round(time.monotonic() - started, 3),
        timed_out=timed_out,
        truncated=stdout.truncated or stderr.truncated,
    )


async def run_checked(spec: CommandSpec) -> CommandResult:
    result = await run_command(spec)
    if not result.ok:
        raise CommandFailedError(spec, result)
    return result
