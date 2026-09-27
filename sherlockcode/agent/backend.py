# Investigation backends: an in-process PydanticAI agent, or an external coding-agent CLI (Claude Code, Codex)
# driven non-interactively over the checked-out repositories.

import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError
from pydantic_ai import AbstractToolset
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage, UsageLimits

from sherlockcode.agent.deps import InvestigationDeps
from sherlockcode.agent.factory import build_investigator
from sherlockcode.agent.prompts import cli_agent_prompt, investigation_prompt
from sherlockcode.config.models import AgentBackend, AgentConfig
from sherlockcode.domain.evidence import EvidenceDraft, EvidenceSource, SourceKind
from sherlockcode.investigation.models import InvestigationAnswer, InvestigationPlan, InvestigationRequest
from sherlockcode.process import CommandResult, CommandSpec, run_command

_JSON_FENCE = re.compile(r"```(?:json)?\s*(?P<body>{.*})\s*```", re.DOTALL)
_COMMIT_CITATION = re.compile(r"^(?:(?P<repo>[\w.-]+)@)?(?P<sha>[0-9a-f]{7,40})$")
_FILE_CITATION = re.compile(r"^(?:(?P<repo>[\w.-]+)/)?(?P<path>.+):(?P<line>\d+)$")


# The CLI backend never produced a JSON object matching `InvestigationAnswer`, even after a retry.
class InvalidCliOutputError(RuntimeError):
    pass


# Produces the final answer of an investigation, given an optional pre-computed plan.
class InvestigationBackend(Protocol):
    async def investigate(
        self,
        request: InvestigationRequest,
        plan: InvestigationPlan | None,
        deps: InvestigationDeps,
        usage: RunUsage,
        limits: UsageLimits,
    ) -> InvestigationAnswer: ...


# Runs the investigation with the in-process PydanticAI agent and its native/MCP toolsets.
@dataclass
class PydanticAiBackend:
    config: AgentConfig
    toolsets: list[AbstractToolset[InvestigationDeps]]
    model: Model | None = None

    async def investigate(
        self,
        request: InvestigationRequest,
        plan: InvestigationPlan | None,
        deps: InvestigationDeps,
        usage: RunUsage,
        limits: UsageLimits,
    ) -> InvestigationAnswer:
        investigator = build_investigator(self.config, self.toolsets)
        result = await investigator.run(
            investigation_prompt(request, plan), deps=deps, model=self.model, usage=usage, usage_limits=limits
        )
        return result.output


# CLI-specific argv building and output extraction for a coding-agent backend.
class CliStrategy(Protocol):
    name: str

    def build_argv(self, config: AgentConfig, prompt: str, output_file: Path) -> list[str]: ...

    def extract_answer_text(self, result: CommandResult, output_file: Path) -> str: ...


class ClaudeCodeStrategy:
    name = "claude-code"
    _default_binary = "claude"
    _allowed_tools = "Read,Grep,Glob,Bash(git log:*),Bash(git show:*),Bash(git diff:*),Bash(git blame:*)"
    _disallowed_tools = "Write,Edit,MultiEdit,NotebookEdit,WebFetch,WebSearch"

    def build_argv(self, config: AgentConfig, prompt: str, output_file: Path) -> list[str]:
        argv = [
            config.cli_command or self._default_binary,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--allowedTools",
            self._allowed_tools,
            "--disallowedTools",
            self._disallowed_tools,
        ]
        if config.model:
            argv += ["--model", config.model]
        return argv + list(config.cli_args)

    def extract_answer_text(self, result: CommandResult, output_file: Path) -> str:
        envelope: dict[str, Any] = json.loads(result.stdout)
        return str(envelope["result"])


class CodexStrategy:
    name = "codex"
    _default_binary = "codex"

    def build_argv(self, config: AgentConfig, prompt: str, output_file: Path) -> list[str]:
        argv = [
            config.cli_command or self._default_binary,
            "exec",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--output-last-message",
            str(output_file),
        ]
        if config.model:
            argv += ["--model", config.model]
        return argv + list(config.cli_args) + [prompt]

    def extract_answer_text(self, result: CommandResult, output_file: Path) -> str:
        if output_file.is_file():
            return output_file.read_text(encoding="utf-8")
        return result.stdout


_STRATEGIES: dict[AgentBackend, CliStrategy] = {
    AgentBackend.CLAUDE_CODE: ClaudeCodeStrategy(),
    AgentBackend.CODEX: CodexStrategy(),
}


def _extract_json(text: str) -> str:
    text = text.strip()
    if match := _JSON_FENCE.search(text):
        return match.group("body")
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def _citation_source(citation: str) -> EvidenceSource:
    if match := _COMMIT_CITATION.match(citation):
        return EvidenceSource(kind=SourceKind.GIT, repository=match.group("repo"), commit=match.group("sha"))
    if match := _FILE_CITATION.match(citation):
        return EvidenceSource(
            kind=SourceKind.FILE,
            repository=match.group("repo"),
            path=match.group("path"),
            line=int(match.group("line")),
        )
    return EvidenceSource(kind=SourceKind.AGENT, path=citation)


def _record_citations(answer: InvestigationAnswer, deps: InvestigationDeps) -> InvestigationAnswer:
    # Replace the CLI's free-text citations (file:line, repo@sha) with recorded evidence ids, keeping the
    # same observed/computed/inferred + evidence id discipline as the PydanticAI backend.
    findings = []
    for finding in answer.findings:
        evidence_ids = []
        for citation in finding.evidence_ids:
            if deps.recorder.has_evidence(citation):
                evidence_ids.append(citation)
                continue
            draft = EvidenceDraft(
                kind=finding.kind, statement=finding.statement, source=_citation_source(citation), excerpt=citation
            )
            evidence_ids.append(deps.recorder.record(draft).id)
        findings.append(finding.model_copy(update={"evidence_ids": evidence_ids}))
    return answer.model_copy(update={"findings": findings})


# Drives an external coding-agent CLI (Claude Code, Codex) non-interactively, read-only, as the
# investigating agent. Planning is skipped: the CLI runs its own tool loop over the checked-out repositories.
@dataclass
class CliAgentBackend:
    config: AgentConfig
    strategy: CliStrategy

    async def investigate(
        self,
        request: InvestigationRequest,
        plan: InvestigationPlan | None,
        deps: InvestigationDeps,
        usage: RunUsage,
        limits: UsageLimits,
    ) -> InvestigationAnswer:
        await deps.checkouts.sync(deps.scope)
        cwd = deps.checkouts.repositories_root
        schema_json = json.dumps(InvestigationAnswer.model_json_schema())
        prompt = cli_agent_prompt(request=request, plan=plan, deps=deps, schema_json=schema_json)

        answer, raw = await self._run_once(prompt, cwd, deps)
        if answer is None:
            retry_prompt = (
                f"{prompt}\n\nYour previous response was not a valid JSON object matching the schema above.\n"
                f"Error: {raw}\nReturn ONLY the corrected JSON object, nothing else."
            )
            answer, raw = await self._run_once(retry_prompt, cwd, deps)
        if answer is None:
            raise InvalidCliOutputError(f"{self.strategy.name} did not return a valid InvestigationAnswer: {raw}")
        return _record_citations(answer, deps)

    async def _run_once(
        self, prompt: str, cwd: Path, deps: InvestigationDeps
    ) -> tuple[InvestigationAnswer | None, str]:
        step = deps.recorder.start_step(f"cli:{self.strategy.name}", {"cwd": str(cwd)})
        error: Exception | None = None
        try:
            with tempfile.TemporaryDirectory() as tmp:
                output_file = Path(tmp) / "last-message.txt"
                spec = CommandSpec(
                    argv=self.strategy.build_argv(self.config, prompt, output_file),
                    cwd=cwd,
                    timeout_seconds=self.config.cli_timeout_seconds,
                )
                result = await run_command(spec)
                if not result.ok:
                    return None, (
                        f"{self.strategy.name} exited with {result.exit_code}: {result.stderr.strip()[:2000]}"
                    )
                try:
                    text = self.strategy.extract_answer_text(result, output_file)
                except (json.JSONDecodeError, KeyError, LookupError) as extraction_error:
                    error = extraction_error
                    return None, f"could not read {self.strategy.name} output: {extraction_error}"
                json_text = _extract_json(text)
                try:
                    return InvestigationAnswer.model_validate_json(json_text), text
                except ValidationError as validation_error:
                    error = validation_error
                    return None, str(validation_error)
        finally:
            deps.recorder.finish_step(step, error)


def build_backend(
    config: AgentConfig, toolsets: list[AbstractToolset[InvestigationDeps]], model: Model | None
) -> InvestigationBackend:
    if config.backend is AgentBackend.PYDANTIC_AI:
        return PydanticAiBackend(config=config, toolsets=toolsets, model=model)
    return CliAgentBackend(config=config, strategy=_STRATEGIES[config.backend])
