"""
tests/test_rate_limit.py

Mirrors tests/test_context_guard.py. The decisive case is `test_real_pilot_429_is_recognised`:
the provider's verbatim 429 wording must be classified as a rate limit, and its
"try again in 2.892s" must be read as a floor rather than the whole wait.
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.rate_limit import (                                    # noqa: E402
    RateLimitRetryMiddleware, is_rate_limit_error, retry_after_seconds, exceeds_limit_alone,
)

# A 429 in the provider's exact wording. The numbers matter: Used + Requested > Limit while
# Requested < Limit, so the failure is recoverable by waiting.
PILOT_429 = (
    "Error code: 429 - {'error': {'message': 'Rate limit reached for test-model in "
    "organization org-XXXXXXXXXXXXXXXXXXXX on tokens per min (TPM): Limit 200000, "
    "Used 70423, Requested 139218. Please try again in 2.892s. Visit "
    "https://platform.openai.com/account/rate-limits to learn more.', 'type': 'tokens', "
    "'param': None, 'code': 'rate_limit_exceeded'}}"
)


class _Err(Exception):
    def __init__(self, msg):
        super().__init__(msg)
        self.message = msg


def test_real_pilot_429_is_recognised():
    assert is_rate_limit_error(_Err(PILOT_429))
    assert abs(retry_after_seconds(_Err(PILOT_429)) - 2.892) < 1e-6


def test_non_rate_limit_errors_are_not_swallowed():
    # A context overflow must reach ContextOverflowClassifier, not be retried here.
    assert not is_rate_limit_error(_Err(
        "This model's maximum context length is 262144 tokens. However, you requested 262145."))
    assert not is_rate_limit_error(_Err("Unsupported parameter: 'top_p' is not supported"))
    assert not is_rate_limit_error(_Err("invalid tool call arguments"))


def test_server_estimate_is_a_floor_not_the_answer():
    """2.892s cannot drain a window that must shed >70k tokens. The wait must be the larger of
    the planned backoff and the server's figure, never the server's figure alone."""
    mw = RateLimitRetryMiddleware()
    assert mw._wait_for(_Err(PILOT_429), 0) == 60.0        # a full rolling-minute window
    assert mw._wait_for(_Err(PILOT_429), 5) == 60.0        # ...every attempt


def test_retries_then_succeeds():
    mw = RateLimitRetryMiddleware(backoff_s=(0.01, 0.01, 0.01))
    calls = {"n": 0}

    def handler(_req):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _Err(PILOT_429)
        return "ok"

    assert mw.wrap_model_call(object(), handler) == "ok"
    assert calls["n"] == 3
    assert mw.waits == 2                                    # waited before each retry


def test_gives_up_after_max_attempts_and_reraises():
    mw = RateLimitRetryMiddleware(max_attempts=3, backoff_s=(0.01,))

    def handler(_req):
        raise _Err(PILOT_429)

    try:
        mw.wrap_model_call(object(), handler)
    except Exception as e:
        assert "rate_limit_exceeded" in str(e)              # the original error, not a wrapper
    else:
        raise AssertionError("should have re-raised")


def test_other_errors_pass_through_immediately():
    mw = RateLimitRetryMiddleware(backoff_s=(5.0,))
    def handler(_req):
        raise _Err("maximum context length")
    t0 = time.monotonic()
    try:
        mw.wrap_model_call(object(), handler)
    except Exception as e:
        assert "maximum context length" in str(e)
    assert time.monotonic() - t0 < 1.0                      # did not sleep


def test_async_path_does_not_block_the_event_loop():
    """awrap_model_call must use asyncio.sleep, because time.sleep would stall every other agent."""
    mw = RateLimitRetryMiddleware(backoff_s=(0.20,))
    calls = {"n": 0}

    async def handler(_req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _Err(PILOT_429)
        return "ok"

    async def other():                                      # must keep running during the wait
        ticks = 0
        for _ in range(20):
            await asyncio.sleep(0.01)
            ticks += 1
        return ticks

    async def main():
        return await asyncio.gather(mw.awrap_model_call(object(), handler), other())

    result, ticks = asyncio.run(main())
    assert result == "ok"
    assert ticks == 20, "event loop was blocked during the rate-limit wait"




# Proactive limiter.
from src.rate_limit import (                                    # noqa: E402
    TokenRateLimiter, TokenRateLimitMiddleware, get_limiter, reset_limiters,
    estimate_request_tokens,
)


class _Resp:
    """Stand-in for ModelResponse: `.result` holds messages carrying usage_metadata."""
    def __init__(self, total=None):
        class _M:
            usage_metadata = {"total_tokens": total} if total else None
        self.result = [_M()]


def test_under_budget_never_waits():
    lim = TokenRateLimiter(limit=2_000_000)
    delay, _ = lim.reserve(139_218)             # the fixture's large request, at an ample budget
    assert delay == 0.0
    assert lim.used() == 139_218


def test_breaching_the_budget_waits():
    lim = TokenRateLimiter(limit=200_000)       # the cap from the 429 fixture
    assert lim.reserve(70_423)[0] == 0.0        # "Used 70423"
    delay, _ = lim.reserve(139_218)             # "Requested 139218" -> 209,641 > 200,000
    assert delay > 0, "the breaching call must be delayed, not sent"
    assert delay <= 61.0


def test_estimate_is_corrected_by_the_providers_own_count():
    """The estimate is biased low. Without correction that bias compounds over hundreds of calls."""
    lim = TokenRateLimiter(limit=1_000_000)
    _, ev = lim.reserve(1_000)                  # we guessed 1k
    assert lim.used() == 1_000
    lim.correct(ev, 50_000)                     # provider says 50k
    assert lim.used() == 50_000


def test_window_drains():
    lim = TokenRateLimiter(limit=1_000, window_s=0.20)
    lim.reserve(900)
    assert lim.used() == 900
    time.sleep(0.30)
    assert lim.used() == 0, "events older than the window must age out"


def test_agents_in_one_process_share_one_budget():
    """Main agent + physics critic + data analyst draw on one org quota. If each middleware kept
    its own state they would together use three times the limit."""
    reset_limiters()
    a = TokenRateLimitMiddleware(limit=100_000, key="test-model")
    b = TokenRateLimitMiddleware(limit=100_000, key="test-model")
    assert a.limiter is b.limiter
    c = TokenRateLimitMiddleware(limit=100_000, key="some-other-model")
    assert c.limiter is not a.limiter, "different models must not share a budget"
    reset_limiters()


def test_single_call_larger_than_the_whole_budget_does_not_hang():
    """Waiting cannot help when one request exceeds the entire budget. It must be sent so the
    429 + reactive retry can handle it, rather than blocking the run forever."""
    lim = TokenRateLimiter(limit=50_000)
    delay, _ = lim.reserve(500_000)
    assert delay == 0.0


def test_middleware_end_to_end_throttles_then_records_actual():
    reset_limiters()
    mw = TokenRateLimitMiddleware(limit=2_000_000, key="t1")
    seen = {}

    class _Req:
        messages, system_message, tools = [], None, []

    def handler(_req):
        seen["called"] = True
        return _Resp(total=123_456)

    t0 = time.monotonic()
    mw.wrap_model_call(_Req(), handler)
    assert seen.get("called")
    assert time.monotonic() - t0 < 1.0                # plenty of budget -> no wait
    assert mw.limiter.used() == 123_456, "window must hold the provider's count, not the estimate"
    reset_limiters()


def test_retry_wraps_limiter_so_retried_attempts_are_also_throttled():
    """Ordering property. build_agent appends retry before limiter, and deepagents treats
    first-in-list as outermost, so a retried attempt still passes through the budget check.
    The other order would let the retry loop fire calls straight past the budget."""
    reset_limiters()
    retry = RateLimitRetryMiddleware(backoff_s=(0.01,))
    limiter = TokenRateLimitMiddleware(limit=2_000_000, key="t2")
    calls = {"n": 0}

    class _Req:
        messages, system_message, tools = [], None, []

    def model(_req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _Err(PILOT_429)
        return _Resp(total=10_000)

    # retry outside, limiter inside, the order build_agent produces
    retry.wrap_model_call(_Req(), lambda r: limiter.wrap_model_call(r, model))
    assert calls["n"] == 2
    assert limiter.limiter.used() == 10_000, "the retried attempt was accounted for"
    reset_limiters()


def test_a_rejected_call_is_refunded_not_left_charged():
    """A 429'd request never reaches the model, so it consumes no quota. If its reservation stayed
    charged, a retry storm would make the limiter sleep for tokens nobody spent."""
    reset_limiters()
    mw = TokenRateLimitMiddleware(limit=2_000_000, key="t3")

    class _Req:
        messages, system_message, tools = [], None, []

    def refuses(_req):
        raise _Err(PILOT_429)

    try:
        mw.wrap_model_call(_Req(), refuses)
    except Exception:
        pass
    assert mw.limiter.used() == 0, "a rejected call must not stay charged to the window"
    reset_limiters()


def test_a_non_rate_limit_failure_stays_charged():
    """Any other failure may have been processed and billed, so its estimate must not be refunded.
    Under-counting is the error that causes the 429 this exists to prevent."""
    reset_limiters()
    mw = TokenRateLimitMiddleware(limit=2_000_000, key="t4")

    class _Req:
        messages, system_message, tools = [], None, []

    def boom(_req):
        raise _Err("maximum context length")

    try:
        mw.wrap_model_call(_Req(), boom)
    except Exception:
        pass
    assert mw.limiter.used() > 0, "a possibly-billed call must stay charged"
    reset_limiters()


def test_pilot_failure_was_recoverable_by_waiting():
    """Requested 139,218 < Limit 200,000, so the window just needed to drain. This is the case
    the retry exists for, and it must not be mistaken for the unrecoverable one."""
    assert not exceeds_limit_alone(_Err(PILOT_429))


def test_a_single_call_bigger_than_the_quota_fails_fast():
    """Requested > Limit: no empty window has room, so every retry fails identically. Burning six
    minutes before dying anyway helps nobody, and the real fix is a config change."""
    unrecoverable = _Err(
        "Error code: 429 - Rate limit reached on tokens per min (TPM): "
        "Limit 200000, Used 0, Requested 260000.")
    assert exceeds_limit_alone(unrecoverable)

    mw = RateLimitRetryMiddleware(backoff_s=(60.0,))
    calls = {"n": 0}

    def handler(_req):
        calls["n"] += 1
        raise unrecoverable

    t0 = time.monotonic()
    try:
        mw.wrap_model_call(object(), handler)
    except Exception:
        pass
    assert calls["n"] == 1, "must not retry when waiting provably cannot help"
    assert time.monotonic() - t0 < 1.0, "must not sleep"


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
            n += 1
    print(f"\n{n} passed")
