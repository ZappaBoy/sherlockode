import json
from typing import Any

import pytest
from pydantic_ai import ModelMessage, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from sherlockode.app import Application
from sherlockode.catalog.catalog import UnknownScopeError
from sherlockode.config.settings import Settings
from sherlockode.investigation.models import InvestigationRequest, InvestigationStatus
from sherlockode.investigation.service import InvestigationService

PLAN = {
    "objective": "Count Python repositories declaring a Python version below 3.12",
    "scope": ["python"],
    "steps": [{"id": "P1", "goal": "Collect declared Python versions", "data_sources": ["analyzer"]}],
}


def _returns(messages: list[ModelMessage]) -> dict[str, Any]:
    return {
        part.tool_name: part.content
        for message in messages
        for part in getattr(message, "parts", [])
        if isinstance(part, ToolReturnPart)
    }


def _answer(evidence_id: str) -> dict[str, Any]:
    return {
        "answer": "1 repository (service-a) declares Python < 3.12.",
        "findings": [
            {
                "statement": "service-a requires Python >=3.11",
                "kind": "observed",
                "evidence_ids": [evidence_id],
                "repositories": ["service-a"],
            }
        ],
        "limitations": [],
    }


def scripted_model() -> FunctionModel:
    attempts = {"final": 0}

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        output_tool = info.output_tools[0].name
        if "run_analyzer" not in {tool.name for tool in info.function_tools}:
            return ModelResponse(parts=[ToolCallPart(output_tool, PLAN)])
        returns = _returns(messages)
        if "run_analyzer" not in returns:
            return ModelResponse(
                parts=[
                    ToolCallPart("run_analyzer", {"analyzer": "python_versions", "repositories": ["python"]}),
                    ToolCallPart("commit_activity", {"request": {"repositories": ["service-a"]}}),
                    ToolCallPart("read_file", {"request": {"repository": "frontend", "path": "../../etc/passwd"}}),
                ]
            )
        attempts["final"] += 1
        if attempts["final"] == 1:
            return ModelResponse(parts=[ToolCallPart(output_tool, _answer("E9999"))])
        results = {r.repository: r for r in returns["run_analyzer"]}
        evidence_id = results["service-a"].data.evidence_ids[0]
        return ModelResponse(parts=[ToolCallPart(output_tool, _answer(evidence_id))])

    return FunctionModel(respond)


async def test_investigation_produces_evidence_backed_persisted_report(settings: Settings) -> None:
    async with Application.open(settings) as app:
        service = InvestigationService(app, model=scripted_model())
        report = await service.investigate(InvestigationRequest(question="How many projects use Python < 3.12?"))
        paths = app.workspace.investigation(report.manifest.id)

    assert report.manifest.status is InvestigationStatus.COMPLETED
    assert report.plan is not None and report.plan.scope == ["python"]
    cited = {e.id: e for e in report.evidence}[report.answer.findings[0].evidence_ids[0]]
    assert (cited.source.repository, cited.source.path, cited.source.line) == ("service-a", "pyproject.toml", 3)
    assert cited.source.commit and cited.step_id

    tools = [step.tool for step in report.steps]
    assert {"run_analyzer", "commit_activity", "read_file"} <= set(tools)
    traversal = next(step for step in report.steps if step.tool == "read_file")
    assert traversal.status == "error" and "not a file" in (traversal.error or "")
    activity = next(e for e in report.evidence if e.kind == "computed" and "commit time" in e.statement)
    assert activity.source.repository == "service-a"

    manifest = json.loads(paths.manifest.read_text())
    assert manifest["status"] == "completed" and manifest["usage"]["requests"] >= 3
    assert paths.plan.is_file() and paths.report_markdown.is_file()
    assert len(json.loads(paths.evidence.read_text())) == len(report.evidence)
    assert len(paths.steps.read_text().splitlines()) == len(report.steps)
    assert "pyproject.toml:3" in paths.report_markdown.read_text()


async def test_unknown_scope_is_rejected_before_running(settings: Settings) -> None:
    async with Application.open(settings) as app:
        service = InvestigationService(app, model=scripted_model())
        with pytest.raises(UnknownScopeError):
            await service.investigate(InvestigationRequest(question="?", scope=["missing"]))
