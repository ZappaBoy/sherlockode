import json
import stat
import textwrap
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.usage import RunUsage, UsageLimits

from sherlockode.agent.backend import (
    ClaudeCodeStrategy,
    CliAgentBackend,
    CodexStrategy,
    InvalidCliOutputError,
    PydanticAiBackend,
    build_backend,
)
from sherlockode.agent.deps import InvestigationDeps
from sherlockode.agent.factory import resolve_model
from sherlockode.app import Application
from sherlockode.config.models import AgentBackend, AgentConfig
from sherlockode.config.settings import Settings
from sherlockode.investigation.models import InvestigationRequest
from sherlockode.investigation.recorder import InvestigationRecorder
from sherlockode.process import CommandResult

_USAGE = RunUsage()
_LIMITS = UsageLimits()


# --- model construction (no network) -----------------------------------------------------------------------


def test_resolve_model_returns_bare_string_without_base_url() -> None:
    config = AgentConfig(model="anthropic:claude-opus-5-5")
    assert resolve_model(config.model, config) == "anthropic:claude-opus-5-5"


def test_resolve_model_builds_openai_compatible_client_for_local_base_url() -> None:
    config = AgentConfig(model="openai:qwen3-coder", base_url="http://localhost:11434/v1")
    model = resolve_model(config.model, config)
    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "qwen3-coder"
    assert str(model.client.base_url) == "http://localhost:11434/v1/"
    assert model.client.api_key == "not-needed"


def test_resolve_model_accepts_bare_model_name_with_base_url() -> None:
    config = AgentConfig(model="qwen3-coder", base_url="http://localhost:8000/v1")
    model = resolve_model(config.model, config)
    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "qwen3-coder"


def test_resolve_model_reads_api_key_from_configured_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_LLM_API_KEY", "secret-token")
    config = AgentConfig(model="qwen3-coder", base_url="http://localhost:8000/v1", api_key_env="LOCAL_LLM_API_KEY")
    model = resolve_model(config.model, config)
    assert isinstance(model, OpenAIChatModel)
    assert model.client.api_key == "secret-token"


def test_resolve_planner_model_falls_back_to_model_when_unset() -> None:
    config = AgentConfig(model="qwen3-coder", planner_model=None, base_url="http://localhost:8000/v1")
    model = resolve_model(config.planner_model or config.model, config)
    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "qwen3-coder"


def test_build_backend_selects_cli_strategy() -> None:
    claude_backend = build_backend(AgentConfig(backend=AgentBackend.CLAUDE_CODE), [], None)
    assert isinstance(claude_backend, CliAgentBackend)
    assert isinstance(claude_backend.strategy, ClaudeCodeStrategy)

    codex_backend = build_backend(AgentConfig(backend=AgentBackend.CODEX), [], None)
    assert isinstance(codex_backend, CliAgentBackend)
    assert isinstance(codex_backend.strategy, CodexStrategy)

    pydantic_backend = build_backend(AgentConfig(), [], None)
    assert isinstance(pydantic_backend, PydanticAiBackend)


# --- CLI argv construction -----------------------------------------------------------------------------------


def test_claude_code_strategy_builds_expected_argv(tmp_path: Path) -> None:
    config = AgentConfig(backend=AgentBackend.CLAUDE_CODE, model="sonnet", cli_args=["--verbose"])
    argv = ClaudeCodeStrategy().build_argv(config, "the prompt", tmp_path / "out.txt")
    assert argv[0] == "claude"
    assert "-p" in argv and "the prompt" in argv
    assert "--output-format" in argv and "json" in argv
    assert "--model" in argv and "sonnet" in argv
    assert argv[-1] == "--verbose"
    assert "--allowedTools" in argv
    assert "--permission-mode" not in argv
    assert "bypassPermissions" not in argv
    disallowed_index = argv.index("--disallowedTools")
    assert argv[disallowed_index + 1] == "Write,Edit,MultiEdit,NotebookEdit,WebFetch,WebSearch"


def test_codex_strategy_builds_expected_argv(tmp_path: Path) -> None:
    output_file = tmp_path / "out.txt"
    config = AgentConfig(backend=AgentBackend.CODEX, cli_command="/usr/bin/codex")
    argv = CodexStrategy().build_argv(config, "the prompt", output_file)
    assert argv[0] == "/usr/bin/codex"
    assert argv[1] == "exec"
    assert "--sandbox" in argv and "read-only" in argv
    assert "--skip-git-repo-check" in argv
    assert "--output-last-message" in argv and str(output_file) in argv
    assert argv[-1] == "the prompt"


def test_extract_answer_text_reads_claude_json_envelope() -> None:
    result = CommandResult(exit_code=0, stdout=json.dumps({"result": "the answer"}), stderr="", duration_seconds=0.1)
    assert ClaudeCodeStrategy().extract_answer_text(result, Path("unused")) == "the answer"


def test_extract_answer_text_reads_codex_last_message_file(tmp_path: Path) -> None:
    output_file = tmp_path / "out.txt"
    output_file.write_text("the answer")
    result = CommandResult(exit_code=0, stdout="", stderr="", duration_seconds=0.1)
    assert CodexStrategy().extract_answer_text(result, output_file) == "the answer"


# --- end-to-end CLI backend against a fake executable ---------------------------------------------------------


def _write_fake_cli(path: Path, script: str) -> None:
    path.write_text(f"#!/usr/bin/env python3\n{script}")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _answer_payload(evidence_citation: str = "service-a/app/main.py:1") -> dict[str, Any]:
    return {
        "answer": "One repository matches.",
        "findings": [
            {
                "statement": "service-a imports fastapi",
                "kind": "observed",
                "evidence_ids": [evidence_citation],
                "repositories": ["service-a"],
            }
        ],
        "limitations": [],
    }


async def _deps(settings: Settings) -> tuple[Application, InvestigationDeps]:
    app_ctx = Application.open(settings)
    app = await app_ctx.__aenter__()
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
    return app, deps


async def test_claude_code_backend_parses_json_envelope_and_records_citations(
    settings: Settings, tmp_path: Path
) -> None:
    fake_claude = tmp_path / "claude"
    _write_fake_cli(
        fake_claude,
        textwrap.dedent(f"""
        import json, sys
        payload = {_answer_payload()!r}
        print(json.dumps({{"result": json.dumps(payload)}}))
        """),
    )
    config = AgentConfig(backend=AgentBackend.CLAUDE_CODE, cli_command=str(fake_claude))
    backend = CliAgentBackend(config=config, strategy=ClaudeCodeStrategy())

    app, deps = await _deps(settings)
    try:
        answer = await backend.investigate(
            InvestigationRequest(question="Which repos use fastapi?"), None, deps, usage=_USAGE, limits=_LIMITS
        )
    finally:
        await app.providers.aclose()

    assert answer.answer == "One repository matches."
    [finding] = answer.findings
    [evidence_id] = finding.evidence_ids
    assert deps.recorder.has_evidence(evidence_id)
    evidence = {e.id: e for e in deps.recorder.evidence}[evidence_id]
    assert evidence.source.repository == "service-a"
    assert evidence.source.path == "app/main.py"
    assert evidence.source.line == 1
    steps = deps.recorder.steps
    assert any(step.tool == "cli:claude-code" and step.status == "ok" for step in steps)


async def test_codex_backend_reads_last_message_file(settings: Settings, tmp_path: Path) -> None:
    fake_codex = tmp_path / "codex"
    _write_fake_cli(
        fake_codex,
        textwrap.dedent(f"""
        import json, sys
        payload = {_answer_payload("service-a@abcdef0123456")!r}
        args = sys.argv
        output_path = args[args.index("--output-last-message") + 1]
        with open(output_path, "w") as fh:
            fh.write(json.dumps(payload))
        """),
    )
    config = AgentConfig(backend=AgentBackend.CODEX, cli_command=str(fake_codex))
    backend = CliAgentBackend(config=config, strategy=CodexStrategy())

    app, deps = await _deps(settings)
    try:
        answer = await backend.investigate(
            InvestigationRequest(question="Which repos use fastapi?"), None, deps, usage=_USAGE, limits=_LIMITS
        )
    finally:
        await app.providers.aclose()

    [finding] = answer.findings
    [evidence_id] = finding.evidence_ids
    evidence = {e.id: e for e in deps.recorder.evidence}[evidence_id]
    assert evidence.source.commit == "abcdef0123456"
    assert evidence.source.repository == "service-a"


async def test_cli_backend_retries_once_on_invalid_json_then_succeeds(settings: Settings, tmp_path: Path) -> None:
    state_file = tmp_path / "attempts"
    fake_claude = tmp_path / "claude"
    _write_fake_cli(
        fake_claude,
        textwrap.dedent(f"""
        import json, os
        state_path = {str(state_file)!r}
        attempts = int(open(state_path).read()) if os.path.exists(state_path) else 0
        attempts += 1
        open(state_path, "w").write(str(attempts))
        if attempts == 1:
            print(json.dumps({{"result": "not json at all"}}))
        else:
            payload = {_answer_payload()!r}
            print(json.dumps({{"result": json.dumps(payload)}}))
        """),
    )
    config = AgentConfig(backend=AgentBackend.CLAUDE_CODE, cli_command=str(fake_claude))
    backend = CliAgentBackend(config=config, strategy=ClaudeCodeStrategy())

    app, deps = await _deps(settings)
    try:
        answer = await backend.investigate(
            InvestigationRequest(question="Retry test"), None, deps, usage=_USAGE, limits=_LIMITS
        )
    finally:
        await app.providers.aclose()

    assert answer.answer == "One repository matches."
    assert int(state_file.read_text()) == 2
    statuses = [step.status for step in deps.recorder.steps if step.tool == "cli:claude-code"]
    assert statuses == ["error", "ok"]


async def test_cli_backend_raises_after_second_invalid_response(settings: Settings, tmp_path: Path) -> None:
    fake_claude = tmp_path / "claude"
    _write_fake_cli(
        fake_claude,
        textwrap.dedent("""
        import json
        print(json.dumps({"result": "still not json"}))
        """),
    )
    config = AgentConfig(backend=AgentBackend.CLAUDE_CODE, cli_command=str(fake_claude))
    backend = CliAgentBackend(config=config, strategy=ClaudeCodeStrategy())

    app, deps = await _deps(settings)
    try:
        with pytest.raises(InvalidCliOutputError):
            await backend.investigate(
                InvestigationRequest(question="Always invalid"), None, deps, usage=_USAGE, limits=_LIMITS
            )
    finally:
        await app.providers.aclose()
