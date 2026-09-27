import logging
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, TypeAdapter
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage, UsageLimits

from sherlockode import __version__
from sherlockode.agent.deps import InvestigationDeps
from sherlockode.agent.factory import build_investigator, build_planner, build_toolsets
from sherlockode.app import Application
from sherlockode.investigation.models import (
    InvestigationPlan,
    InvestigationReport,
    InvestigationRequest,
    InvestigationStatus,
    Manifest,
)
from sherlockode.investigation.recorder import InvestigationRecorder
from sherlockode.investigation.rendering import render_markdown

logger = logging.getLogger(__name__)

_USAGE = TypeAdapter(RunUsage)


class AgentRun(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    deps: InvestigationDeps
    usage: RunUsage
    limits: UsageLimits


class InvestigationService:
    """Runs the investigation lifecycle: scope, plan, investigate, and persist a reproducible record."""

    def __init__(self, app: Application, model: Model | None = None) -> None:
        self._app = app
        self._model = model

    async def investigate(self, request: InvestigationRequest) -> InvestigationReport:
        settings = self._app.settings
        catalog = await self._app.catalog()
        scope = catalog.resolve_scope(request.scope)
        recorder = InvestigationRecorder(self._app.workspace.new_investigation())
        manifest = Manifest(
            id=recorder.paths.id,
            question=request.question,
            requested_scope=request.scope,
            resolved_scope=[repository.name for repository in scope],
            model=settings.agent.model,
            planner_model=settings.agent.planner_model,
            version=__version__,
            configuration=settings.redacted() if settings.storage.save_config_snapshot else {},
        )
        recorder.save_manifest(manifest)
        deps = InvestigationDeps(
            settings=settings,
            catalog=catalog,
            providers=self._app.providers,
            git=self._app.git,
            checkouts=self._app.checkouts,
            analyzers=self._app.analyzers,
            sandbox=self._app.sandbox,
            recorder=recorder,
            scope=scope,
        )
        try:
            report = await self._run(request, deps, manifest)
        except BaseException as error:
            manifest.status = InvestigationStatus.FAILED
            manifest.error = f"{type(error).__name__}: {error}"
            raise
        finally:
            manifest.finished_at = datetime.now(UTC)
            recorder.save_manifest(manifest)
            recorder.save_evidence()
        self._persist(report, recorder)
        return report

    async def _run(
        self, request: InvestigationRequest, deps: InvestigationDeps, manifest: Manifest
    ) -> InvestigationReport:
        config = self._app.settings.agent
        limits = self._app.settings.limits
        run = AgentRun(
            deps=deps,
            usage=RunUsage(),
            limits=UsageLimits(request_limit=limits.max_agent_requests, tool_calls_limit=limits.max_tool_calls),
        )
        toolsets = build_toolsets(self._app.providers, sandbox_enabled=deps.sandbox is not None)
        plan = None
        if request.planning if request.planning is not None else config.planning:
            planner = build_planner(config)
            plan = await self._execute(planner, request.question, run)
            deps.recorder.save_plan(plan)
        investigator = build_investigator(config, toolsets)
        answer = await self._execute(investigator, _investigation_prompt(request, plan), run)
        manifest.status = InvestigationStatus.COMPLETED
        manifest.usage = _USAGE.dump_python(run.usage, mode="json")
        return InvestigationReport(
            manifest=manifest,
            plan=plan,
            answer=answer,
            evidence=deps.recorder.evidence,
            steps=deps.recorder.steps,
        )

    async def _execute[T](self, agent: Agent[InvestigationDeps, T], prompt: str, run: AgentRun) -> T:
        result = await agent.run(prompt, deps=run.deps, model=self._model, usage=run.usage, usage_limits=run.limits)
        return result.output

    def _persist(self, report: InvestigationReport, recorder: InvestigationRecorder) -> None:
        paths = recorder.paths
        paths.report_json.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        paths.report_markdown.write_text(render_markdown(report), encoding="utf-8")
        keep = self._app.settings.storage.keep_investigations
        if keep:
            self._app.workspace.prune_investigations(keep)


def _investigation_prompt(request: InvestigationRequest, plan: InvestigationPlan | None) -> str:
    sections = [f"Question: {request.question}"]
    if request.scope:
        sections.append(f"Requested scope: {', '.join(request.scope)}")
    if plan:
        sections.append(f"Investigation plan:\n{plan.model_dump_json(indent=2)}")
    return "\n\n".join(sections)
