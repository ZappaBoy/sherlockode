import threading
import time
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter

from sherlockode.domain.evidence import Evidence, EvidenceDraft
from sherlockode.investigation.models import InvestigationPlan, Manifest, StepRecord, StepStatus
from sherlockode.workspace.layout import InvestigationPaths

_current_step: ContextVar[StepRecord | None] = ContextVar("current_step", default=None)
_EVIDENCE_LIST = TypeAdapter(list[Evidence])


class InvestigationRecorder:
    """Keeps the investigation trace and evidence ledger, persisting them as they are produced."""

    def __init__(self, paths: InvestigationPaths) -> None:
        self.paths = paths
        self._evidence: dict[str, Evidence] = {}
        self._steps: list[StepRecord] = []
        self._lock = threading.Lock()

    @property
    def evidence(self) -> list[Evidence]:
        return list(self._evidence.values())

    @property
    def steps(self) -> list[StepRecord]:
        return list(self._steps)

    def has_evidence(self, evidence_id: str) -> bool:
        return evidence_id in self._evidence

    def record(self, draft: EvidenceDraft) -> Evidence:
        step = _current_step.get()
        with self._lock:
            evidence = Evidence(
                **draft.model_dump(), id=f"E{len(self._evidence) + 1:04d}", step_id=step.id if step else None
            )
            self._evidence[evidence.id] = evidence
        if step:
            step.evidence_ids.append(evidence.id)
        return evidence

    def start_step(self, tool: str, arguments: dict[str, Any]) -> StepRecord:
        with self._lock:
            step = StepRecord(
                id=f"S{len(self._steps) + 1:04d}",
                tool=tool,
                arguments=arguments,
                started_at=datetime.now(UTC),
            )
            self._steps.append(step)
        _current_step.set(step)
        return step

    def finish_step(self, step: StepRecord, error: BaseException | None = None) -> None:
        step.duration_seconds = round((datetime.now(UTC) - step.started_at).total_seconds(), 3)
        step.status = StepStatus.ERROR if error else StepStatus.OK
        step.error = f"{type(error).__name__}: {error}" if error else None
        _current_step.set(None)
        with self.paths.steps.open("a", encoding="utf-8") as stream:
            stream.write(step.model_dump_json() + "\n")

    def save_manifest(self, manifest: Manifest) -> None:
        _write_model(self.paths.manifest, manifest)

    def save_plan(self, plan: InvestigationPlan) -> None:
        _write_model(self.paths.plan, plan)

    def save_evidence(self) -> None:
        self.paths.evidence.write_bytes(_EVIDENCE_LIST.dump_json(self.evidence, indent=2))

    def next_sandbox_run(self) -> str:
        return f"run-{len(list(self.paths.sandbox_runs.iterdir())) + 1:03d}-{int(time.time())}"


def _write_model(path: Path, model: BaseModel) -> None:
    path.write_text(model.model_dump_json(indent=2), encoding="utf-8")
