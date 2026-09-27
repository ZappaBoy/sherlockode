from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from .models import WorkspaceConfig


class WorkspaceLayout(BaseModel):
    root: Path
    repositories: Path
    investigations: Path
    artifacts: Path
    reports: Path
    analysis: Path
    generated: Path
    cache: Path


class WorkspaceManager:
    def __init__(self, config: WorkspaceConfig) -> None:
        self._config = config

    def build_layout(self) -> WorkspaceLayout:
        root = self._config.root
        artifacts = root / self._config.artifacts_dir
        return WorkspaceLayout(
            root=root,
            repositories=root / self._config.repositories_dir,
            investigations=root / self._config.investigations_dir,
            artifacts=artifacts,
            reports=artifacts / "reports",
            analysis=artifacts / "analysis",
            generated=artifacts / "generated",
            cache=root / self._config.cache_dir,
        )

    def ensure_directories(self) -> WorkspaceLayout:
        layout = self.build_layout()
        for directory in layout.model_dump().values():
            directory.mkdir(parents=True, exist_ok=True)
        return layout
