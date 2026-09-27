from pathlib import Path

from sherlockcode.config.models import SandboxBackend, SandboxConfig
from sherlockcode.sandbox.base import Sandbox
from sherlockcode.sandbox.docker import DockerSandbox, PathMapper
from sherlockcode.sandbox.local import LocalSandbox


def build_sandbox(config: SandboxConfig, workspace: Path) -> Sandbox | None:
    if not config.enabled:
        return None
    if config.backend is SandboxBackend.LOCAL:
        return LocalSandbox(config)
    return DockerSandbox(config, PathMapper(workspace, config.host_workspace))
