import shutil
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from sherlockcode.domain.repository import RepositoryRef

_REPOSITORIES_DIR = "repositories"
_INVESTIGATIONS_DIR = "investigations"
_ARTIFACTS_DIR = "artifacts"
_ID_DATE_FORMAT = "%Y%m%d"


# Filesystem layout for a single investigation.
class InvestigationPaths(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    root: Path

    @property
    def manifest(self) -> Path:
        return self.root / "manifest.json"

    @property
    def plan(self) -> Path:
        return self.root / "plan.json"

    @property
    def steps(self) -> Path:
        return self.root / "steps.jsonl"

    @property
    def evidence(self) -> Path:
        return self.root / "evidence.json"

    @property
    def report_json(self) -> Path:
        return self.root / "report.json"

    @property
    def report_markdown(self) -> Path:
        return self.root / "report.md"

    @property
    def sandbox_runs(self) -> Path:
        return self.root / "sandbox-runs"

    def initialize(self) -> "InvestigationPaths":
        self.sandbox_runs.mkdir(parents=True, exist_ok=True)
        return self


# Filesystem layout for the runtime workspace: repository checkouts, investigations and artifacts.
class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def repositories(self) -> Path:
        return self.root / _REPOSITORIES_DIR

    @property
    def investigations(self) -> Path:
        return self.root / _INVESTIGATIONS_DIR

    @property
    def artifacts(self) -> Path:
        return self.root / _ARTIFACTS_DIR

    def initialize(self) -> None:
        self.repositories.mkdir(parents=True, exist_ok=True)
        self.investigations.mkdir(parents=True, exist_ok=True)
        (self.artifacts / "reports").mkdir(parents=True, exist_ok=True)

    def investigation(self, investigation_id: str) -> InvestigationPaths:
        return InvestigationPaths(id=investigation_id, root=self.investigations / investigation_id)

    def new_investigation(self) -> InvestigationPaths:
        return self.investigation(self._next_investigation_id()).initialize()

    def list_investigations(self) -> list[InvestigationPaths]:
        if not self.investigations.is_dir():
            return []
        names = sorted(entry.name for entry in self.investigations.iterdir() if entry.is_dir())
        return [self.investigation(name) for name in names]

    def prune_investigations(self, keep: int) -> None:
        investigations = self.list_investigations()
        for paths in investigations[:-keep] if keep > 0 else investigations:
            shutil.rmtree(paths.root, ignore_errors=True)

    def checkout_path(self, repository: RepositoryRef) -> Path:
        # Path a repository is checked out to, confined to `repositories` regardless of `..` in the inputs.
        segments = _safe_segments(repository.provider, repository.full_path or repository.name)
        return self.repositories.joinpath(*segments)

    def _next_investigation_id(self) -> str:
        today = datetime.now(UTC).strftime(_ID_DATE_FORMAT)
        sequence = sum(1 for paths in self.list_investigations() if paths.id.startswith(today)) + 1
        return f"{today}-{sequence:03d}"


def _safe_segments(*values: str) -> list[str]:
    return [part for value in values for part in value.split("/") if part not in ("", ".", "..")]
