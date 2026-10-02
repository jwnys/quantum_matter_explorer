"""
qme/context_guard.py

Bridge a vLLM context-overflow 400 into the recovery deepagents already ships.

deepagents' `SummarizationMiddleware` recovers from context overflow (deterministically clip the
trailing tool-message batch, summarize, retry), but only when the error is a
`langchain_core.exceptions.ContextOverflowError`. `langchain_openai` raises that only when the
provider message contains one of a few OpenAI/Anthropic-specific substrings
(`_handle_openai_bad_request`, base.py). vLLM's wording, "This model's maximum context length is
N tokens ... reduce the length of the input prompt", matches none of them (vLLM omits the
`context_length_exceeded` code that real OpenAI sets), so the raw `openai.BadRequestError` would
propagate uncaught and kill the run with "Run failed" (main.py). Neither library recognises the
vLLM wording, so it is bridged here.

This middleware catches that 400 and, if it is a context overflow, re-raises it as
`ContextOverflowError` so deepagents' own (pairing-safe, tested) recovery takes over. It adds no
trimming or retry logic of its own: that lives in deepagents, which wraps this middleware
(first-in-list = outermost), so a re-raised `ContextOverflowError` reaches its `except`.
"""
from __future__ import annotations

import openai
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.exceptions import ContextOverflowError

# Lowercased substrings that mark a context-length overflow across providers. The two that catch the local
# vLLM build (which real OpenAI's substrings miss) are "maximum context length" and "reduce the length of
# the input prompt". The rest keep cloud/other-server wordings covered so this stays provider-general.
OVERFLOW_MARKERS = (
    "maximum context length",
    "reduce the length of the input prompt",
    "reduce the length of the messages",
    "context_length_exceeded",
    "context length exceeded",
    "input tokens exceed",
    "exceeds the context window",
    "prompt is too long",
    "too many tokens",
)


def is_context_overflow_message(exc: BaseException) -> bool:
    """True if the exception reads like a context-length overflow (provider-general substring match)."""
    text = f"{getattr(exc, 'message', '') or ''} {exc}".lower()
    return any(m in text for m in OVERFLOW_MARKERS)


class ContextOverflowClassifier(AgentMiddleware):
    """Re-raise a vLLM context-overflow 400 as `ContextOverflowError` so deepagents' summarization
    middleware (which wraps this one) recovers instead of the run crashing. Purely a re-classifier:
    it does not trim or retry, that is deepagents' job, one layer out."""

    def _reraise_if_overflow(self, e: openai.BadRequestError):
        if is_context_overflow_message(e):
            raise ContextOverflowError(str(getattr(e, "message", e))) from e
        raise e

    def wrap_model_call(self, request, handler):
        try:
            return handler(request)
        except ContextOverflowError:
            raise                                    # already classified (e.g. cloud), outer recovery handles it
        except openai.BadRequestError as e:
            self._reraise_if_overflow(e)

    async def awrap_model_call(self, request, handler):
        try:
            return await handler(request)
        except ContextOverflowError:
            raise
        except openai.BadRequestError as e:
            self._reraise_if_overflow(e)
