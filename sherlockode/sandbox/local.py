import logging
import os
import re
import sys

from sherlockode.config.models import SandboxConfig
from sherlockode.process import CommandSpec, run_command
from sherlockode.sandbox.base import ExecutionRequest, ExecutionResult, Sandbox

logger = logging.getLogger(__name__)

_SIZE = re.compile(r"^(\d+(?:\.\d+)?)([kmg]?)b?$", re.IGNORECASE)
_UNITS = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}
_BASE_ENV = ("PATH", "LANG", "LC_ALL", "TZ")


def parse_size(value: str) -> int:
    match = _SIZE.match(value.strip())
    if not match:
        raise ValueError(f"invalid size: {value}")
    return int(float(match.group(1)) * _UNITS[match.group(2).lower()])


# Runs scripts as resource-limited host subprocesses with a scrubbed environment.
# This is a development fallback only: it does not isolate the filesystem or network.
class LocalSandbox(Sandbox):
    def __init__(self, config: SandboxConfig) -> None:
        super().__init__(config)
        logger.warning("local sandbox backend enabled: agent-generated code is NOT isolated")

    @property
    def isolated(self) -> bool:
        return False

    async def _run(self, request: ExecutionRequest) -> ExecutionResult:
        interpreter = sys.executable if request.language.interpreter == "python3" else "sh"
        environment = {key: os.environ[key] for key in (*_BASE_ENV, *self.config.passthrough_env) if key in os.environ}
        timeout = self.timeout_for(request)
        script = request.run_directory / request.language.filename
        spec = CommandSpec(
            argv=["prlimit", *self._limits(timeout), "--", interpreter, str(script)],
            cwd=request.repository or request.run_directory,
            env=environment | {"HOME": str(request.run_directory), "OUTPUT_DIR": str(request.run_directory / "output")},
            timeout_seconds=timeout,
            max_output_bytes=self.config.max_output_bytes,
        )
        result = await run_command(spec)
        return ExecutionResult(**result.model_dump(exclude={"ok"}))

    def _limits(self, timeout: int) -> list[str]:
        return [f"--cpu={timeout}", f"--as={parse_size(self.config.memory)}"]
