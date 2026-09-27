import os
import shutil
from pathlib import Path

import pytest

from sherlockode.config.models import SandboxConfig
from sherlockode.sandbox import ExecutionRequest, ScriptLanguage
from sherlockode.sandbox.docker import DockerSandbox, PathMapper
from sherlockode.sandbox.local import LocalSandbox, parse_size


@pytest.mark.skipif(shutil.which("prlimit") is None, reason="prlimit not available")
async def test_local_sandbox_runs_script_and_collects_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_TOKEN", "leak")
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "data.txt").write_text("a\nb\n")
    script = (
        "import os, pathlib\n"
        "print(len(pathlib.Path('data.txt').read_text().splitlines()), os.environ.get('SECRET_TOKEN'))\n"
        "pathlib.Path(os.environ['OUTPUT_DIR'], 'result.json').write_text('{}')\n"
    )
    request = ExecutionRequest(
        script=script, language=ScriptLanguage.PYTHON, repository=repository, run_directory=tmp_path / "run"
    )

    result = await LocalSandbox(SandboxConfig(backend="local")).execute(request)

    assert result.exit_code == 0, result.stderr
    assert result.stdout.strip() == "2 None"
    assert result.output_files == ["result.json"]


@pytest.mark.skipif(shutil.which("prlimit") is None, reason="prlimit not available")
async def test_local_sandbox_enforces_timeout(tmp_path: Path) -> None:
    request = ExecutionRequest(script="sleep 5", run_directory=tmp_path / "run", timeout_seconds=1)

    result = await LocalSandbox(SandboxConfig(backend="local")).execute(request)

    assert result.timed_out


def test_docker_command_is_locked_down(tmp_path: Path) -> None:
    config = SandboxConfig(host_workspace=Path("/host/ws"), passthrough_env=["LANG"])
    sandbox = DockerSandbox(config, PathMapper(tmp_path, config.host_workspace))
    request = ExecutionRequest(script="ls", repository=tmp_path / "repositories" / "r", run_directory=tmp_path / "run")

    argv = sandbox._docker_argv("name", request, timeout=30)

    command = " ".join(argv)
    for flag in ("--network none", "--read-only", "--cap-drop ALL", "no-new-privileges", "--user 65534:65534"):
        assert flag in command
    assert "source=/host/ws/repositories/r,target=/repo,readonly" in command
    assert argv[-7:] == ["sherlockode-sandbox:latest", "timeout", "-s", "KILL", "30", "sh", "/work/script.sh"]


def test_parse_size() -> None:
    assert parse_size("1g") == 1024**3
    assert parse_size("512m") == 512 * 1024**2


@pytest.mark.skipif(not os.environ.get("SHERLOCKODE_SANDBOX_IMAGE"), reason="set SHERLOCKODE_SANDBOX_IMAGE to run")
async def test_docker_sandbox_isolation(tmp_path: Path) -> None:
    repository = tmp_path / "repositories" / "r"
    repository.mkdir(parents=True)
    (repository / "a.txt").write_text("x")
    script = (
        "import os, pathlib, socket\n"
        "try:\n    open('x', 'w'); print('writable')\nexcept OSError: print('read-only')\n"
        "try:\n    socket.create_connection(('1.1.1.1', 53), timeout=2); print('online')\n"
        "except OSError: print('offline')\n"
        "print(os.getuid())\n"
        "pathlib.Path(os.environ['OUTPUT_DIR'], 'out.txt').write_text('ok')\n"
    )
    config = SandboxConfig(image=os.environ["SHERLOCKODE_SANDBOX_IMAGE"])
    sandbox = DockerSandbox(config, PathMapper(tmp_path, None))
    request = ExecutionRequest(
        script=script, language=ScriptLanguage.PYTHON, repository=repository, run_directory=tmp_path / "run"
    )

    result = await sandbox.execute(request)

    assert result.stdout.split() == ["read-only", "offline", "65534"], result.stderr
    assert result.output_files == ["out.txt"]
