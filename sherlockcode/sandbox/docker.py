import uuid
from pathlib import Path

from sherlockcode.config.models import SandboxConfig
from sherlockcode.process import CommandResult, CommandSpec, run_command
from sherlockcode.sandbox.base import REPOSITORY_MOUNT, WORK_MOUNT, ExecutionRequest, ExecutionResult, Sandbox


# Translates workspace paths to host paths when the application itself runs in a container.
class PathMapper:
    def __init__(self, workspace: Path, host_workspace: Path | None) -> None:
        self._workspace = workspace.resolve()
        self._host_workspace = host_workspace

    def to_host(self, path: Path) -> Path:
        if self._host_workspace is None:
            return path.resolve()
        return self._host_workspace / path.resolve().relative_to(self._workspace)


# One disposable, locked-down container per execution.
class DockerSandbox(Sandbox):
    def __init__(self, config: SandboxConfig, paths: PathMapper) -> None:
        super().__init__(config)
        self._paths = paths

    async def _run(self, request: ExecutionRequest) -> ExecutionResult:
        name = f"sherlockcode-{uuid.uuid4().hex[:12]}"
        timeout = self.timeout_for(request)
        spec = CommandSpec(
            argv=self._docker_argv(name, request, timeout),
            timeout_seconds=timeout + 30,
            max_output_bytes=self.config.max_output_bytes,
        )
        try:
            result = await run_command(spec)
        finally:
            await run_command(CommandSpec(argv=[self.config.docker_binary, "rm", "-f", name], timeout_seconds=30))
        return _to_execution_result(result, timed_out=result.timed_out or result.exit_code == 137)

    def _docker_argv(self, name: str, request: ExecutionRequest, timeout: int) -> list[str]:
        config = self.config
        argv = [
            config.docker_binary,
            "run",
            "--rm",
            "--name",
            name,
            "--network",
            config.network,
            "--cpus",
            str(config.cpus),
            "--memory",
            config.memory,
            "--memory-swap",
            config.memory,
            "--pids-limit",
            str(config.pids_limit),
            "--user",
            config.user,
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=256m",
            "--env",
            "HOME=/tmp",
            "--env",
            f"OUTPUT_DIR={WORK_MOUNT}/output",
            "--mount",
            f"type=bind,source={self._paths.to_host(request.run_directory)},target={WORK_MOUNT}",
            "--workdir",
            REPOSITORY_MOUNT if request.repository else WORK_MOUNT,
        ]
        if config.runtime:
            argv += ["--runtime", config.runtime]
        if request.repository:
            source = self._paths.to_host(request.repository)
            argv += ["--mount", f"type=bind,source={source},target={REPOSITORY_MOUNT},readonly"]
        for variable in config.passthrough_env:
            argv += ["--env", variable]
        script = f"{WORK_MOUNT}/{request.language.filename}"
        return [
            *argv,
            config.image,
            "timeout",
            "-s",
            "KILL",
            str(timeout),
            request.language.interpreter,
            script,
        ]


def _to_execution_result(result: CommandResult, *, timed_out: bool) -> ExecutionResult:
    return ExecutionResult(
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        duration_seconds=result.duration_seconds,
        timed_out=timed_out,
        truncated=result.truncated,
    )
