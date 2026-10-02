"""
qme/tool_error_guard.py

Hand a tool's unhandled exception back to the agent as text, instead of ending the run.

The failure this protects against: `langgraph`'s `_default_handle_tool_errors` re-raises
anything that is not a `ToolException` (langgraph/prebuilt/tool_node.py:391), so one bad tool
argument can end a whole study. Some inputs are structurally unanswerable, for example a grep
pattern containing a NUL byte: `subprocess` forbids NUL in argv, and deepagents passes the
pattern straight to it (deepagents/backends/filesystem.py:655, ValueError: embedded null byte).
Every other mistake the agent makes already comes back to it as an error message it can recover
from, so this guard removes that one asymmetry rather than special-casing individual inputs.

It cannot be fixed in the tool. The built-in tools belong to deepagents in site-packages, which
is outside this repo and would be overwritten by a reinstall, and neither `create_deep_agent`
nor `create_agent` exposes a `handle_tool_errors` parameter. So it is caught from outside, in
the same `wrap_tool_call` hook `qme/agent.py` already uses.

What it must not swallow. Some exceptions are not a tool reporting bad input, they are the
framework signalling something. All of them are `Exception` subclasses, so a bare
`except Exception` catches them, and the exclusion list below is load-bearing, not decoration:

  * `GraphBubbleUp`, the base of langgraph's control flow: `GraphInterrupt`, `NodeInterrupt`
    (human gates), `ParentCommand` (control handoff) and `GraphDrained`. Swallowing these makes
    the review gates stop working silently.
  * `GraphRecursionError`, the loop limit. Swallowing it lets the agent loop past its own limit.
  * `NodeCancelledError`. Swallowing it means a cancelled run keeps running.
  * `ContextOverflowError`. `ContextOverflowClassifier` exists in order to raise this so
    deepagents' trim-and-retry recovery can catch it (qme/context_guard.py). It reaches a tool
    call because the subagent tool runs a whole sub-agent that makes model calls, so swallowing
    it here would quietly disable that guard.

`KeyboardInterrupt` and `SystemExit` derive from `BaseException`, so `except Exception` already lets
them through. Do not widen to `BaseException`.

Registered on the harness profile in `qme/agent.py:_register_safety_profile`, not appended per
agent, for the reason that function's docstring gives: deepagents auto-creates a
`general-purpose` subagent with its own middleware list that per-agent appends keep missing.
"""
from __future__ import annotations

import logging

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage

logger = logging.getLogger("qme.tool_error_guard")

# Longest exception text passed on to the agent. A tool can raise with a whole file in the
# message. The full text always reaches logs/ via logger.exception regardless.
MAX_DETAIL = 2000

# Resolved by name so that a rename upstream degrades to "one fewer exclusion, warned in the log"
# rather than "the guard fails to import and is absent".
PASSTHROUGH_SPECS: tuple[tuple[str, str], ...] = (
    ("langgraph.errors", "GraphBubbleUp"),
    ("langgraph.errors", "GraphRecursionError"),
    ("langgraph.errors", "NodeCancelledError"),
    ("langchain_core.exceptions", "ContextOverflowError"),
)


def _resolve_passthrough() -> tuple[type[BaseException], ...]:
    """The exception types that must keep propagating. Missing ones are warned about, not fatal."""
    out: list[type[BaseException]] = []
    for mod, name in PASSTHROUGH_SPECS:
        try:
            out.append(getattr(__import__(mod, fromlist=[name]), name))
        except Exception:
            logger.warning("ToolErrorGuard: %s.%s not importable, so it is not in the "
                           "passthrough set and that condition would be reported to the agent "
                           "instead of handled", mod, name)
    return tuple(out)


class ToolErrorGuard(AgentMiddleware):
    """Turn an unhandled tool exception into an ordinary error `ToolMessage`, so the agent can fix
    its arguments and keep going. Mirrors SkillGateMiddleware.wrap_tool_call (qme/agent.py)."""

    def __init__(self) -> None:
        super().__init__()
        self._passthrough = _resolve_passthrough()

    def wrap_tool_call(self, request, handler):
        tc = request.tool_call or {}
        try:
            return handler(request)
        except self._passthrough:
            raise
        except Exception as exc:
            name = tc.get("name") or ""
            # logger.exception, not logger.warning: a swallowed exception that leaves no traceback
            # is how a real bug in our own tools would hide behind this guard.
            logger.exception("ToolErrorGuard: %s raised %s, returned to the agent as an error, "
                             "run continues", name, type(exc).__name__)
            detail = f"{type(exc).__name__}: {exc}"
            if len(detail) > MAX_DETAIL:
                detail = detail[:MAX_DETAIL] + " …[truncated]"
            return ToolMessage(
                content=(f"Tool `{name}` raised and did not run: {detail}\n"
                         "This is a failure of the call itself, not a result. Change the arguments "
                         "or use another route. Do not repeat it unchanged."),
                tool_call_id=tc.get("id", ""),
                name=name,
                status="error",
            )
