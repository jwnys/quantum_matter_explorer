"""
src/obs/callback.py

DeepAgentCallbackHandler bridges LangChain/LangGraph callback events into the
project's loggers (full transcript plus per-event stats).

Pass it via `config={"callbacks": [handler]}` to `agent.stream(...)`. Callbacks
propagate to subagent (`task`) runs too, so their LLM/tool activity is captured.
Runs are tagged by their metadata when available, else "agent".

Everything is wrapped in try/except: logging must never break the run.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from .logger import InteractionLogger
from .stats_logger import StatsLogger


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # content blocks
        out = []
        for b in content:
            if isinstance(b, dict):
                out.append(b.get("text") or b.get("content") or "")
            else:
                out.append(str(b))
        return "".join(out)
    return str(content)


class DeepAgentCallbackHandler(BaseCallbackHandler):
    """Translate LLM + tool callback events into InteractionLogger / StatsLogger."""

    raise_error = False  # never let a logging bug abort the agent

    def __init__(self, default_agent: str = "agent") -> None:
        super().__init__()
        self.default_agent = default_agent
        self._runs: dict[UUID, dict[str, Any]] = {}

    # --- helpers ---
    def _ilog(self) -> InteractionLogger:
        return InteractionLogger.get()

    def _slog(self) -> StatsLogger:
        return StatsLogger.get()

    def _agent_of(self, kwargs: dict, metadata: dict | None = None) -> str:
        # deepagents stamps each subagent run with metadata["lc_agent_name"] (+ run_name) and
        # configurable["ls_agent_type"]="subagent" (middleware/subagents.py). The main agent
        # carries none. LangChain delivers the run metadata to callbacks in kwargs["metadata"],
        # so it has to be read from there: deepagents never sets the kwargs name/tags fields, and
        # relying on them collapses every call to "agent", losing the per-agent breakdown and
        # making subagent calls look like context drops on the context_over_time plot.
        md = metadata if metadata is not None else (kwargs.get("metadata") or {})
        if isinstance(md, dict):
            name = md.get("lc_agent_name")
            if name:
                return str(name)
            if md.get("ls_agent_type") == "subagent":
                return "subagent"
        for t in (kwargs.get("tags") or []):           # legacy fallback (non-deepagents paths)
            if isinstance(t, str) and ("subagent" in t or "task" in t):
                return t
        return kwargs.get("name") or self.default_agent

    # --- chat model / LLM ---
    def on_chat_model_start(self, serialized, messages, *, run_id=None, **kwargs):
        try:
            flat = messages[0] if messages and isinstance(messages[0], list) else (messages or [])
            text = "\n".join(_text_of(getattr(m, "content", "")) for m in flat)
            self._runs[run_id] = {"t": time.monotonic(), "prompt_chars": len(text),
                                  "agent": self._agent_of(kwargs)}
            self._ilog().log(self._runs[run_id]["agent"], "prompt", text)
        except Exception:
            pass

    def on_llm_start(self, serialized, prompts, *, run_id=None, **kwargs):
        try:
            text = "\n".join(prompts or [])
            self._runs[run_id] = {"t": time.monotonic(), "prompt_chars": len(text),
                                  "agent": self._agent_of(kwargs)}
            self._ilog().log(self._runs[run_id]["agent"], "prompt", text)
        except Exception:
            pass

    def on_llm_end(self, response, *, run_id=None, **kwargs):
        try:
            r = self._runs.pop(run_id, {})
            agent = r.get("agent", self.default_agent)
            dt = time.monotonic() - r.get("t", time.monotonic())
            text, in_tok, out_tok, tot_tok, model = "", None, None, None, ""
            try:
                gen = response.generations[0][0]
                msg = getattr(gen, "message", None)
                text = _text_of(getattr(gen, "text", "") or (getattr(msg, "content", "") if msg else ""))
                um = getattr(msg, "usage_metadata", None) if msg else None
                if um:
                    in_tok, out_tok, tot_tok = um.get("input_tokens"), um.get("output_tokens"), um.get("total_tokens")
                meta = getattr(msg, "response_metadata", {}) if msg else {}
                model = meta.get("model_name") or (getattr(response, "llm_output", None) or {}).get("model_name", "") or ""
            except Exception:
                text = _text_of(response)[:4000]
            self._ilog().log(agent, "response", text)
            self._slog().llm_call(
                agent=agent, iteration=0, provider="", model=model, duration_s=dt,
                prompt_chars=r.get("prompt_chars", 0), response_chars=len(text),
                input_tokens=in_tok, output_tokens=out_tok, total_tokens=tot_tok,
            )
        except Exception:
            pass

    def on_llm_error(self, error, *, run_id=None, **kwargs):
        try:
            self._ilog().error(self.default_agent, f"LLM error: {error}")
            self._runs.pop(run_id, None)
        except Exception:
            pass

    # --- tools ---
    def on_tool_start(self, serialized, input_str, *, run_id=None, inputs=None, **kwargs):
        try:
            name = (serialized or {}).get("name", "tool")
            agent = self._agent_of(kwargs)
            self._runs[run_id] = {"t": time.monotonic(), "name": name,
                                  "args": inputs if isinstance(inputs, dict) else input_str, "agent": agent}
            self._ilog().log(agent, "tool_call", f"{name} ← {input_str}", extra={"tool": name})
        except Exception:
            pass

    def on_tool_end(self, output, *, run_id=None, **kwargs):
        try:
            r = self._runs.pop(run_id, {})
            agent = r.get("agent", self.default_agent)
            name = r.get("name", "tool")
            out = output if isinstance(output, str) else _text_of(getattr(output, "content", output))
            dt = time.monotonic() - r.get("t", time.monotonic())
            self._ilog().log(agent, "tool_result", out, extra={"tool": name})
            self._slog().tool_call(
                agent=agent, tool=name, iteration=0, round_idx=0,
                args=r.get("args", {}), duration_s=dt, ok=True, result_chars=len(out),
            )
        except Exception:
            pass

    def on_tool_error(self, error, *, run_id=None, **kwargs):
        try:
            r = self._runs.pop(run_id, {})
            agent = r.get("agent", self.default_agent)
            name = r.get("name", "tool")
            dt = time.monotonic() - r.get("t", time.monotonic())
            self._ilog().error(agent, f"tool {name} error: {error}")
            self._slog().tool_call(
                agent=agent, tool=name, iteration=0, round_idx=0,
                args=r.get("args", {}), duration_s=dt, ok=False, result_chars=0,
            )
        except Exception:
            pass
