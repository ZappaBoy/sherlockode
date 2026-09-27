import pytest
from jinja2 import UndefinedError

from sherlockcode.agent.deps import InvestigationDeps
from sherlockcode.agent.prompts import (
    _ENV,
    cli_agent_prompt,
    environment_description,
    investigation_prompt,
    investigator_instructions,
    planner_instructions,
)
from sherlockcode.app import Application
from sherlockcode.config.settings import Settings
from sherlockcode.investigation.models import InvestigationPlan, InvestigationRequest, PlanStep
from sherlockcode.investigation.recorder import InvestigationRecorder


def test_investigator_instructions_render_without_variables() -> None:
    text = investigator_instructions()
    assert "Evidence discipline" in text


def test_planner_instructions_render_without_variables() -> None:
    text = planner_instructions()
    assert "investigation plan" in text


def test_investigation_prompt_includes_scope_and_plan() -> None:
    request = InvestigationRequest(question="How many repos use FastAPI?", scope=["python"])
    plan = InvestigationPlan(
        objective="Count FastAPI users",
        scope=["python"],
        steps=[PlanStep(id="P1", goal="grep dependencies", data_sources=["analyzer"])],
    )
    text = investigation_prompt(request, plan)
    assert "How many repos use FastAPI?" in text
    assert "Requested scope: python" in text
    assert '"objective": "Count FastAPI users"' in text


def test_investigation_prompt_omits_scope_and_plan_when_absent() -> None:
    text = investigation_prompt(InvestigationRequest(question="Q"), None)
    assert "Requested scope" not in text
    assert "Investigation plan" not in text


def test_environment_template_requires_all_variables_strict_undefined() -> None:
    """StrictUndefined must reject a render that is missing a variable the template needs."""
    with pytest.raises(UndefinedError):
        _ENV.get_template("environment.md.jinja").render(scope_count=1)


async def test_environment_description_and_cli_prompt_render_from_deps(settings: Settings) -> None:
    async with Application.open(settings) as app:
        catalog = await app.catalog()
        scope = catalog.resolve_scope([])
        recorder = InvestigationRecorder(app.workspace.new_investigation())
        deps = InvestigationDeps(
            settings=app.settings,
            catalog=catalog,
            providers=app.providers,
            git=app.git,
            checkouts=app.checkouts,
            analyzers=app.analyzers,
            sandbox=app.sandbox,
            recorder=recorder,
            scope=scope,
        )
        description = environment_description(deps)
        assert "Investigation scope" in description
        assert "Analyzers (run_analyzer)" in description

        request = InvestigationRequest(question="Which repos are Python?")
        schema_json = '{"title": "InvestigationAnswer"}'
        prompt = cli_agent_prompt(request=request, plan=None, deps=deps, schema_json=schema_json)
        assert "Which repos are Python?" in prompt
        assert schema_json in prompt
        assert "service-a" in prompt
        assert "Respond with ONLY a single JSON object" in prompt
