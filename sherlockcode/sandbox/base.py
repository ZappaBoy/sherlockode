from abc import ABC, abstractmethod
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from sherlockcode.config.models import SandboxConfig

REPOSITORY_MOUNT = "/repo"
WORK_MOUNT = "/work"


class ScriptLanguage(StrEnum):
    SHELL = "shell"
    PYTHON = "python"

    @property
    def filename(self) -> str:
        return "script.py" if self is ScriptLanguage.PYTHON else "script.sh"

    @property
    def interpreter(self) -> str:
        return "python3" if self is ScriptLanguage.PYTHON else "sh"


class ExecutionRequest(BaseModel):
    script: str
    language: ScriptLanguage = ScriptLanguage.SHELL
    repository: Path | None = Field(default=None, description="Checkout mounted read-only as the working directory.")
    run_directory: Path = Field(
        description="Writable scratch directory; files written to `output/` are kept as artifacts."
    )
    timeout_seconds: int | None = None


class ExecutionResult(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    truncated: bool = False
    output_files: list[str] = Field(default_factory=list)


# Executes untrusted, agent-generated code away from the main application's privileges.
class Sandbox(ABC):
    def __init__(self, config: SandboxConfig) -> None:
        self.config = config

    @property
    def isolated(self) -> bool:
        return True

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        output = request.run_directory / "output"
        output.mkdir(parents=True, exist_ok=True)
        # The sandbox runs as an unprivileged user that differs from the application's user.
        output.chmod(0o777)
        (request.run_directory / request.language.filename).write_text(request.script, encoding="utf-8")
        result = await self._run(request)
        files = sorted(str(path.relative_to(output)) for path in output.rglob("*") if path.is_file())
        return result.model_copy(update={"output_files": files})

    def timeout_for(self, request: ExecutionRequest) -> int:
        return min(request.timeout_seconds or self.config.timeout_seconds, self.config.timeout_seconds)

    @abstractmethod
    async def _run(self, request: ExecutionRequest) -> ExecutionResult: ...
