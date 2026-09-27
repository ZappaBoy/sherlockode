from pathlib import Path

from sherlockode.config.models import SandboxBackend, SandboxConfig
from sherlockode.sandbox.base import Sandbox
from sherlockode.sandbox.docker import DockerSandbox, PathMapper
from sherlockode.sandbox.local import LocalSandbox


def build_sandbox(config: SandboxConfig, workspace: Path) -> Sandbox | None:
    if not config.enabled:
        return None
    if config.backend is SandboxBackend.LOCAL:
        return LocalSandbox(config)
    return DockerSandbox(config, PathMapper(workspace, config.host_workspace))
