"""Contract tests for the context-overflow classifier.

Pins the two properties that matter: (1) the predicate recognises vLLM's overflow wording
and the legacy OpenAI/Anthropic wordings, while not firing on unrelated 400s; (2) the
middleware re-raises an overflow BadRequestError as ContextOverflowError (so deepagents'
recovery takes over) but passes everything else through untouched.

    python -m pytest tests/test_context_guard.py
"""
import sys
from pathlib import Path

import httpx
import openai
from langchain_core.exceptions import ContextOverflowError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qme.context_guard import (  # noqa: E402
    ContextOverflowClassifier,
    is_context_overflow_message,
)

# The verbatim wording vLLM uses for a context overflow.
VLLM_MSG = (
    "This model's maximum context length is 262144 tokens. However, you requested 0 output tokens "
    "and your prompt contains at least 262145 input tokens, for a total of at least 262145 tokens. "
    "Please reduce the length of the input prompt or the number of requested output tokens. "
    "(parameter=input_tokens, value=262145)"
)


def bre(msg: str) -> openai.BadRequestError:
    """A real openai.BadRequestError carrying `msg` (needs an httpx.Response)."""
    resp = httpx.Response(400, request=httpx.Request("POST", "http://vllm/v1/chat/completions"))
    return openai.BadRequestError(msg, response=resp, body={"message": msg})


def run_mw(exc=None, ret="ok"):
    """Drive ContextOverflowClassifier.wrap_model_call with a handler that raises `exc` or returns `ret`.
    Returns ('raised', ExcType) or ('returned', value)."""
    mw = ContextOverflowClassifier()

    def handler(_req):
        if exc is not None:
            raise exc
        return ret

    class Req:
        def override(self, **_k):
            return self

    try:
        out = mw.wrap_model_call(Req(), handler)
        return ("returned", out)
    except BaseException as e:  # noqa: BLE001
        return ("raised", type(e))


# Predicate: recognises overflow wordings, ignores unrelated 400s.

def test_vllm_maximum_context_length_is_overflow():
    assert is_context_overflow_message(bre(VLLM_MSG))


def test_legacy_context_length_exceeded_is_overflow():
    assert is_context_overflow_message(bre("Error: {'code': 'context_length_exceeded'}"))


def test_legacy_prompt_is_too_long_is_overflow():
    assert is_context_overflow_message(bre("prompt is too long"))


def test_legacy_exceeds_context_window_is_overflow():
    assert is_context_overflow_message(bre("This request exceeds the context window of the model"))


def test_legacy_input_tokens_exceed_limit_is_overflow():
    assert is_context_overflow_message(bre("Input tokens exceed the configured limit of 200000"))


def test_json_schema_error_is_not_overflow():
    assert not is_context_overflow_message(bre("Invalid schema for response_format 'json_schema'"))


def test_unsupported_response_format_is_not_overflow():
    assert not is_context_overflow_message(
        bre("'response_format' of type 'json_schema' is not supported"))


def test_tool_arg_validation_is_not_overflow():
    assert not is_context_overflow_message(bre("Invalid value for 'tool_choice': expected a string"))


# Middleware: reclassify overflow, pass everything else through.

def test_overflow_400_reraised_as_context_overflow_error():
    kind, t = run_mw(exc=bre(VLLM_MSG))
    assert (kind, t) == ("raised", ContextOverflowError), f"{kind} {getattr(t, '__name__', t)}"


def test_unrelated_400_propagates_unchanged():
    kind, t = run_mw(exc=bre("Invalid schema for response_format 'json_schema'"))
    assert kind == "raised" and issubclass(t, openai.BadRequestError) \
        and not issubclass(t, ContextOverflowError), f"{kind} {getattr(t, '__name__', t)}"


def test_normal_return_passes_through():
    kind, out = run_mw(ret="normal-response")
    assert (kind, out) == ("returned", "normal-response"), f"{kind} {out}"


def test_already_classified_error_propagates_unchanged():
    kind, t = run_mw(exc=ContextOverflowError("already classified"))
    assert (kind, t) == ("raised", ContextOverflowError), f"{kind} {getattr(t, '__name__', t)}"


if __name__ == "__main__":
    failures = []
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"OK    {name}")
            except AssertionError as e:
                print(f"FAIL  {name}  {e}")
                failures.append(name)
    print("\nFAILURES:", failures or "none")
    raise SystemExit(1 if failures else 0)
