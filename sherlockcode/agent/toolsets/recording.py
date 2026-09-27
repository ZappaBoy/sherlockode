from typing import Any

import httpx
from pydantic_ai import RunContext, ToolFailed, WrapperToolset
from pydantic_ai.toolsets import ToolsetTool

from sherlockcode.agent.deps import InvestigationDeps
from sherlockcode.process import CommandFailedError

_OPERATIONAL_ERRORS = (CommandFailedError, httpx.HTTPError, OSError, ValueError, LookupError)


# Records every tool call as an investigation step and reports operational failures to the model.
class RecordingToolset(WrapperToolset[InvestigationDeps]):
    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[InvestigationDeps],
        tool: ToolsetTool[InvestigationDeps],
    ) -> Any:
        recorder = ctx.deps.recorder
        step = recorder.start_step(name, tool_args)
        try:
            result = await super().call_tool(name, tool_args, ctx, tool)
        except _OPERATIONAL_ERRORS as error:
            recorder.finish_step(step, error)
            raise ToolFailed(f"{type(error).__name__}: {error}") from error
        except BaseException as error:
            recorder.finish_step(step, error)
            raise
        recorder.finish_step(step)
        return result
