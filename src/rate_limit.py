"""
src/rate_limit.py

Stay under a provider's tokens-per-minute cap. Two independent mechanisms, both opt-in:

    TokenRateLimitMiddleware   proactive: count tokens in a rolling 60 s window and sleep before
                               a call that would breach a configured budget.
                                   agent.tokens_per_minute: 1800000
    RateLimitRetryMiddleware   reactive: if a 429 arrives anyway, wait out the window and retry.
                                   agent.rate_limit_retry: 6

They are complementary and the belt-and-braces pairing is deliberate: the proactive limiter cannot
be exact (see the estimate caveats below), so the reactive one is what makes the run survive the
cases the estimate gets wrong. Use both, or the retry alone. The limiter alone is not sufficient.

Why any of this. An agent turn re-sends the entire conversation as input, so a single request's
input grows monotonically over the run while output stays small. Once the conversation is large
enough, two back-to-back calls sum past the provider's per-minute cap, a 429 is structurally
certain, and an unattended run dies hours in. A provider 429 can also outlast the SDK's own
retries, so this module waits out the advertised window instead of failing the run.

Why the openai SDK's own retries are not enough. It honours `Retry-After` when that is 0-60 s, and
otherwise backs off 0.5*2^n capped at 8 s (`openai/_base_client.py:_calculate_retry_timeout`,
`openai/_constants.py:MAX_RETRY_DELAY`). Those caps are tuned for transient blips, so even 10
retries buy under a minute in total, and the server's own `Retry-After` estimate is optimistic for
a window that must shed tens of thousands of tokens. The reactive middleware here escalates to a
full window instead, which is the only wait guaranteed to clear a rolling minute. The SDK's
retries still cover everything else (flex `resource_unavailable`, connection resets), so they stay
useful for what they are good at.

What the proactive limiter cannot do (read before trusting it):
  * It cannot make 429s impossible. The pre-call cost is an estimate:
    `count_tokens_approximately` undercounts against a real tokenizer (the same undercount that
    makes `agent.summary_headroom` necessary), tool schemas are billed but absent from the message
    list, and the output length is unknown until the response arrives. Each call's estimate is
    corrected from the provider's own usage numbers once they land, so the error does not
    accumulate, but the call that was just sent may still have been under-counted.
  * It cannot see other consumers of the same quota, such as another script on the same API key
    or a second run launched separately. Set the budget somewhat below the true cap to absorb both.
  * It is per-process, so a parallel sweep of a rate-limited model must still use one worker.
"""
from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from collections import deque

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages.utils import count_tokens_approximately

logger = logging.getLogger("qme.rate_limit")

WINDOW_S = 60.0          # providers meter TPM over a rolling minute

# How much `count_tokens_approximately` undercounts on this workload. The counter assumes
# ~4 chars per token, which is calibrated for common English prose. This workload is Julia,
# JSON and numeric arrays, which tokenize far denser (around 2.6 chars per token in practice),
# so real token counts run roughly 1.5x the estimate at the median and higher in the worst
# case. 1.6 sits just above that median: over-estimating only costs a little wall-clock, while
# under-estimating causes the 429 this exists to prevent. To re-derive the factor for a
# different workload, compare prompt_chars vs input_tokens in a run's logs/stats.jsonl.
UNDERCOUNT = 1.6

# Waits per attempt, in seconds. The quota is metered over a rolling minute, so ~60 s is simply
# the right answer: it is the only duration guaranteed to clear the meter no matter how the
# tokens were distributed, and anything shorter is a bet that the breach was marginal. The total
# is about six minutes over six attempts, nothing to an unattended multi-hour run, and far
# cheaper than the run dying with hours of completed work behind it. Do not shorten these to
# "fail faster". The one case where waiting is genuinely useless, a single request larger than
# the whole limit, is detected separately and fails immediately instead of burning six minutes
# (see `exceeds_limit_alone`).
BACKOFF_S = (60.0, 60.0, 60.0, 60.0, 60.0, 60.0)

# Substrings marking a rate limit as opposed to any other 429/400. Kept provider-general: DeepSeek
# and Anthropic use different wording for the same condition.
_RATE_MARKERS = ("rate_limit", "rate limit", "tokens per min", "tokens per minute",
                 "requests per min", "too many requests", "quota")


def is_rate_limit_error(exc: BaseException) -> bool:
    """True if this exception is a provider rate limit (not a context overflow, not a bad request).

    Checked by type first (`openai.RateLimitError` is unambiguous), then by message, so providers
    that surface a 429 through a generic error class are still caught.
    """
    try:
        import openai
        if isinstance(exc, openai.RateLimitError):
            return True
    except Exception:                                    # openai not installed / import failure
        pass
    text = f"{getattr(exc, 'message', '') or ''} {exc}".lower()
    if "429" in text and "rate" in text:
        return True
    return any(m in text for m in _RATE_MARKERS)


def retry_after_seconds(exc: BaseException) -> float | None:
    """The provider's own requested wait, if it gave one.

    Two sources: the `Retry-After` response header, and the human-readable "Please try again in
    2.892s" that OpenAI puts in the message body. Treated as a floor, never as the whole wait:
    the server can ask for a few seconds when the window actually needs to shed tens of
    thousands of tokens.
    """
    resp = getattr(exc, "response", None)
    hdrs = getattr(resp, "headers", None)
    if hdrs:
        for k in ("retry-after", "Retry-After", "x-ratelimit-reset-tokens"):
            v = hdrs.get(k) if hasattr(hdrs, "get") else None
            if v:
                try:
                    return float(str(v).rstrip("s"))
                except (TypeError, ValueError):
                    pass
    m = re.search(r"try again in\s+([0-9.]+)\s*(ms|s)\b",
                  f"{getattr(exc, 'message', '') or ''} {exc}", re.I)
    if m:
        val = float(m.group(1))
        return val / 1000.0 if m.group(2).lower() == "ms" else val
    return None


def exceeds_limit_alone(exc: BaseException) -> bool:
    """True if one request is bigger than the entire per-minute quota.

    Waiting cannot fix this: even a completely empty window has no room, so every retry would
    fail identically and the run would just burn six minutes before dying anyway. Detected from
    the numbers the provider puts in the message, e.g.

        "on tokens per min (TPM): Limit 200000, Used 70423, Requested 250000"

    where Requested > Limit is the unrecoverable case. The fix for it is a smaller conversation
    (agent.max_input_tokens) or a bigger quota, so the error message says so rather than
    silently retrying.
    """
    m = re.search(r"limit\s+(\d+).*?requested\s+(\d+)",
                  f"{getattr(exc, 'message', '') or ''} {exc}", re.I | re.S)
    return bool(m) and int(m.group(2)) > int(m.group(1))


class RateLimitRetryMiddleware(AgentMiddleware):
    """Wait out a rate-limit 429 and retry the model call, instead of letting it kill the run.

    Wraps the model call because that is where tokens are billed and where the 429 surfaces. It
    does not touch any other error: a context overflow still reaches `ContextOverflowClassifier`
    and deepagents' summarisation recovery, and a genuine bad request still fails fast.
    """

    def __init__(self, max_attempts: int = 6, backoff_s=BACKOFF_S,
                 window_s: float = WINDOW_S) -> None:
        super().__init__()
        self.max_attempts = max(1, int(max_attempts))
        self.backoff_s = tuple(backoff_s)
        self.window_s = float(window_s)
        self.waits = 0                 # counters so a run can report how much it sat on the limit
        self.waited_s = 0.0

    def _wait_for(self, exc: BaseException, attempt: int) -> float:
        """How long to sleep after failure number `attempt` (0-based)."""
        planned = self.backoff_s[min(attempt, len(self.backoff_s) - 1)]
        asked = retry_after_seconds(exc)
        # The server's figure is a floor, not the answer: it assumes the window drains linearly,
        # which it does not when one huge request is what breached the cap.
        wait = max(planned, asked or 0.0)
        return min(wait, self.window_s * 2)              # never sit longer than two windows

    def _log(self, exc: BaseException, attempt: int, wait: float) -> None:
        self.waits += 1
        self.waited_s += wait
        logger.warning(
            "rate limited (attempt %d/%d): waiting %.1fs for the window to drain, then retrying. %s",
            attempt + 1, self.max_attempts, wait,
            str(getattr(exc, "message", exc))[:200])

    def wrap_model_call(self, request, handler):
        last: BaseException | None = None
        for attempt in range(self.max_attempts):
            try:
                return handler(request)
            except Exception as e:
                if not is_rate_limit_error(e):
                    raise                                # not ours, let it propagate untouched
                if exceeds_limit_alone(e):
                    logger.error(
                        "a single request exceeds the entire per-minute quota, so retrying "
                        "cannot help. Lower agent.max_input_tokens so the conversation is "
                        "compacted sooner, or raise the provider quota. %s",
                        str(getattr(e, "message", e))[:200])
                    raise
                last = e
                if attempt == self.max_attempts - 1:
                    break
                wait = self._wait_for(e, attempt)
                self._log(e, attempt, wait)
                time.sleep(wait)
        logger.error("still rate limited after %d attempts (%.0fs waited), giving up",
                     self.max_attempts, self.waited_s)
        raise last                                       # type: ignore[misc]

    async def awrap_model_call(self, request, handler):
        last: BaseException | None = None
        for attempt in range(self.max_attempts):
            try:
                return await handler(request)
            except Exception as e:
                if not is_rate_limit_error(e):
                    raise                                # not ours, let it propagate untouched
                if exceeds_limit_alone(e):
                    logger.error(
                        "a single request exceeds the entire per-minute quota, so retrying "
                        "cannot help. Lower agent.max_input_tokens so the conversation is "
                        "compacted sooner, or raise the provider quota. %s",
                        str(getattr(e, "message", e))[:200])
                    raise
                last = e
                if attempt == self.max_attempts - 1:
                    break
                wait = self._wait_for(e, attempt)
                self._log(e, attempt, wait)
                # This has to be asyncio.sleep: time.sleep would block the event loop and stall
                # every other agent in the process, not just this call.
                await asyncio.sleep(wait)
        logger.error("still rate limited after %d attempts (%.0fs waited), giving up",
                     self.max_attempts, self.waited_s)
        raise last                                       # type: ignore[misc]


# --- proactive: don't send the call that would breach the budget ---

class TokenRateLimiter:
    """A rolling-window token budget, shared by every agent in the process.

    The provider meters per organisation, so the main agent, the physics critic and the data
    analyst all draw on one quota. Each builds its own middleware instance, so the state has to
    live here (module-level registry below) rather than on the middleware, otherwise three agents
    would each believe they had the full budget and together use three times it.
    """

    def __init__(self, limit: int, window_s: float = WINDOW_S) -> None:
        self.limit = int(limit)
        self.window_s = float(window_s)
        self._events: "deque[list[float]]" = deque()   # [send_time, tokens]; list => mutable
        self._lock = threading.Lock()
        self.waits = 0
        self.waited_s = 0.0

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_s
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def used(self) -> int:
        """Tokens charged to the current rolling window."""
        with self._lock:
            self._prune(time.monotonic())
            return int(sum(e[1] for e in self._events))

    def reserve(self, cost: int) -> "tuple[float, list[float]]":
        """Charge `cost` to the budget and return (seconds to sleep first, event to correct later).

        Reserving before sleeping is what makes concurrent callers serialise correctly: each takes
        its slot in the window, so two agents cannot both conclude there is room for one more call.
        """
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            used = sum(e[1] for e in self._events)
            delay = 0.0
            if used + cost > self.limit and self._events:
                # Wait until enough of the oldest events age out. Walking them gives one precise
                # sleep instead of a poll loop.
                need = used + cost - self.limit
                freed = 0.0
                delay = -1.0
                for ts, tok in self._events:
                    freed += tok
                    if freed >= need:
                        delay = max(0.0, (ts + self.window_s) - now) + 0.05
                        break
                if delay < 0:
                    # Even an empty window cannot fit this call: the single request exceeds the
                    # whole budget. Waiting cannot help, so send it and let the 429 + reactive
                    # retry deal with it. Blocking forever would be strictly worse.
                    logger.warning(
                        "single call (~%d tokens) exceeds the entire %d tok/min budget - sending "
                        "anyway. Lower agent.summary_headroom so the context stops growing past "
                        "the rate limit, or raise agent.tokens_per_minute if the quota allows.",
                        cost, self.limit)
                    delay = 0.0
            # Stamped when the call will actually be sent, so the window reflects what the
            # provider sees rather than when we decided to send it.
            ev = [now + delay, float(cost)]
            self._events.append(ev)
            if delay:
                self.waits += 1
                self.waited_s += delay
            return delay, ev

    def release(self, ev: "list[float]") -> None:
        """Un-charge a reservation for a call the provider rejected.

        A 429'd request is refused before it is processed, so it consumes no quota. Leaving its
        estimate in the window would make every later call see a budget that is more used than it
        really is, and the limiter would then sleep for tokens nobody ever spent. The error
        compounds across a retry storm, which is exactly when accuracy matters most.
        """
        with self._lock:
            ev[1] = 0.0

    def correct(self, ev: "list[float]", actual: int) -> None:
        """Replace an estimate with the provider's own count once the response arrives.

        This is what keeps the window honest over a long run: the estimate is biased low, and
        without correction that bias would compound across hundreds of calls.
        """
        with self._lock:
            ev[1] = float(actual)


_LIMITERS: "dict[str, TokenRateLimiter]" = {}
_REGISTRY_LOCK = threading.Lock()


def get_limiter(key: str, limit: int) -> TokenRateLimiter:
    """One limiter per quota. `key` identifies what the provider meters (use the model name), so
    two different models do not end up sharing a single budget."""
    with _REGISTRY_LOCK:
        lim = _LIMITERS.get(key)
        if lim is None or lim.limit != int(limit):
            lim = TokenRateLimiter(limit)
            _LIMITERS[key] = lim
        return lim


def reset_limiters() -> None:
    """Drop all limiter state. Tests only."""
    with _REGISTRY_LOCK:
        _LIMITERS.clear()


def estimate_request_tokens(request, output_allowance: int = 1000) -> int:
    """Approximate what this call will be billed, deliberately on the high side.

    Under-estimating causes the 429 this exists to prevent, while over-estimating only costs a little
    wall-clock. The asymmetry is resolved in favour of waiting.
    """
    msgs = list(getattr(request, "messages", None) or [])
    sysmsg = getattr(request, "system_message", None)
    if sysmsg is not None:
        msgs = [sysmsg, *msgs]
    try:
        n = int(count_tokens_approximately(msgs))
    except Exception:                       # accounting must never break a run
        return 0
    # Tool schemas are re-sent and billed every call but are not in `messages`. ~120 tokens per
    # tool is a rough but stable stand-in for their JSON schemas.
    n += 120 * len(getattr(request, "tools", None) or [])
    return int(n * UNDERCOUNT) + int(output_allowance)


def response_tokens(response) -> "int | None":
    """Total tokens the provider billed, if it reported them."""
    for msg in (getattr(response, "result", None) or []):
        um = getattr(msg, "usage_metadata", None)
        if um:
            total = um.get("total_tokens")
            if total:
                return int(total)
            return int(um.get("input_tokens", 0)) + int(um.get("output_tokens", 0))
    return None


class TokenRateLimitMiddleware(AgentMiddleware):
    """Sleep before a model call that would push the rolling window past the configured budget.

    Wrapping the model call is the right layer: tokens are billed per model request, and this is
    the last point at which the full outgoing message list is visible.
    """

    def __init__(self, limit: int, key: str = "default",
                 output_allowance: int = 1000, max_sleep_s: float = WINDOW_S * 1.5) -> None:
        super().__init__()
        self.limiter = get_limiter(key, limit)
        self.output_allowance = int(output_allowance)
        self.max_sleep_s = float(max_sleep_s)

    def _before(self, request):
        est = estimate_request_tokens(request, self.output_allowance)
        delay, ev = self.limiter.reserve(est)
        if delay > self.max_sleep_s:
            # A wait longer than the window means the bookkeeping has drifted. Cap it and say so,
            # rather than stalling an unattended run on a number nobody will see.
            logger.warning("rate-limit wait %.1fs capped to %.1fs", delay, self.max_sleep_s)
            delay = self.max_sleep_s
        if delay > 0:
            logger.info("token budget: waiting %.1fs before a ~%d-token call (%d/%d tok in window)",
                        delay, est, self.limiter.used(), self.limiter.limit)
        return delay, ev

    def _after(self, response, ev) -> None:
        actual = response_tokens(response)
        if actual:
            self.limiter.correct(ev, actual)

    def wrap_model_call(self, request, handler):
        delay, ev = self._before(request)
        if delay > 0:
            time.sleep(delay)
        try:
            response = handler(request)
        except Exception as e:
            # Only a rejected call is refunded. Any other failure may have been processed and
            # billed, so its estimate stays charged: over-counting costs a little wall-clock,
            # under-counting causes the 429 this exists to prevent.
            if is_rate_limit_error(e):
                self.limiter.release(ev)
            raise
        self._after(response, ev)
        return response

    async def awrap_model_call(self, request, handler):
        delay, ev = self._before(request)
        if delay > 0:
            # This has to be asyncio.sleep: time.sleep would block the event loop and stall
            # every other agent in the process, not just this call.
            await asyncio.sleep(delay)
        try:
            response = await handler(request)
        except Exception as e:
            if is_rate_limit_error(e):
                self.limiter.release(ev)
            raise
        self._after(response, ev)
        return response
