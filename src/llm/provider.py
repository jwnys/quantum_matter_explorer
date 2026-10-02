"""
src/llm/provider.py
Provider-agnostic LLM factory.

Supports:
  - vllm       (local, auto-launched server)
  - openai, anthropic, groq, deepseek  (cloud)
  - openai_compatible  (any OpenAI-style endpoint, e.g. LM Studio)
"""

from __future__ import annotations

import os
import logging
from typing import Any

from langchain_core.language_models import BaseChatModel

logger = logging.getLogger("qme.llm_provider")


# Providers that need a local backend server (auto-launched by main.py).
LOCAL_PROVIDERS = frozenset({"vllm"})

_PROVIDER_BUILDERS = {
    "openai":            lambda sub: _build_openai(sub),
    "anthropic":         lambda sub: _build_anthropic(sub),
    "groq":              lambda sub: _build_groq(sub),
    "openai_compatible": lambda sub: _build_openai_compatible(sub),
    "vllm":              lambda sub: _build_vllm(sub),
    "deepseek":          lambda sub: _build_deepseek(sub),
}


def _common_defaults(cfg: dict[str, Any]) -> dict[str, Any]:
    """Per-agent defaults applied to every agent before its specific override.

    `agent_models.default: {...}` keeps the user from having to repeat common
    keys (like `thinking_mode: true`) on every agent. Per-agent overrides win.
    """
    am = cfg.get("agent_models") or {}
    if isinstance(am, dict):
        return dict(am.get("default", {}) or {})
    return {}


def resolve_agent_provider(cfg: dict[str, Any], agent_name: str) -> tuple[str, dict[str, Any]]:
    """Return the (provider, merged_sub_config) an agent will use.

    Resolution order (later wins):
      1. cfg.<provider>             provider-level defaults (model, base_url, ...)
      2. cfg.agent_models.default   common per-agent defaults (e.g. thinking_mode)
      3. cfg.agent_models.<agent>   per-agent override

    A `provider:` key in (2) or (3) switches backends entirely (e.g. global
    default vLLM, the physics-critic on Anthropic).
    """
    default_provider = cfg.get("provider", "vllm")
    am = cfg.get("agent_models") or {}
    common = _common_defaults(cfg)
    agent_specific = {}
    if agent_name and isinstance(am, dict):
        agent_specific = dict(am.get(agent_name, {}) or {})

    # Agent-specific keys override the common defaults.
    merged_override = {**common, **agent_specific}

    provider = merged_override.pop("provider", default_provider)
    sub = dict(cfg.get(provider, {}) or {})
    sub.update(merged_override)
    return provider, sub


def active_providers(cfg: dict[str, Any]) -> set[str]:
    """Set of providers any agent will actually use (default + overrides).

    Used by main.py to launch each local backend at most once, and skip the
    launch entirely if no agent will use it.
    """
    default_provider = cfg.get("provider", "vllm")
    providers = {default_provider}

    # agent_models.default can switch the default provider for all agents
    common = _common_defaults(cfg)
    if common.get("provider"):
        providers.add(common["provider"])

    for name, override in (cfg.get("agent_models") or {}).items():
        if name == "default":
            continue
        if isinstance(override, dict) and override.get("provider"):
            providers.add(override["provider"])
    return providers


def models_per_provider(cfg: dict[str, Any]) -> dict[str, set[str]]:
    """For each provider, the distinct models any agent will actually load.

    Lets the local launcher pre-warm every model that agents will load, so
    we don't pay first-use latency on the hot path.
    """
    out: dict[str, set[str]] = {}
    default_provider = cfg.get("provider", "vllm")
    default_sub = cfg.get(default_provider, {}) or {}
    default_model = default_sub.get("model")
    if default_model:
        out.setdefault(default_provider, set()).add(default_model)

    common = _common_defaults(cfg)
    if common.get("provider"):
        prov = common["provider"]
        sub = dict(cfg.get(prov, {}) or {})
        sub.update({k: v for k, v in common.items() if k != "provider"})
        if sub.get("model"):
            out.setdefault(prov, set()).add(sub["model"])

    for name, override in (cfg.get("agent_models") or {}).items():
        if name == "default" or not isinstance(override, dict):
            continue
        # Apply the same merge order as resolve_agent_provider
        merged = {**common, **override}
        prov = merged.pop("provider", default_provider)
        sub = dict(cfg.get(prov, {}) or {})
        sub.update(merged)
        if sub.get("model"):
            out.setdefault(prov, set()).add(sub["model"])
    return out


def build_llm(cfg: dict[str, Any], agent_name: str = "") -> BaseChatModel:
    """
    Return a LangChain BaseChatModel for the named agent.

    cfg is the top-level `llm` section of config.yaml. Per-agent overrides
    from `agent_models[agent_name]` may switch the provider entirely via a
    `provider:` key; all other override keys merge on top of that provider's
    sub-config.
    """
    provider, sub = resolve_agent_provider(cfg, agent_name)
    logger.debug("Building LLM for agent=%r provider=%s model=%s",
                 agent_name, provider, sub.get("model"))

    builder = _PROVIDER_BUILDERS.get(provider)
    if builder is None:
        raise ValueError(f"Unknown LLM provider: {provider!r}")
    return builder(sub)


# Provider builders.

def _build_openai(sub: dict[str, Any]) -> BaseChatModel:
    """OpenAI cloud. Key from the env var named by `api_key_env`, never from config.

    `temperature` is only sent when the config sets it explicitly. OpenAI's REASONING models
    (o-series, gpt-5.x) reject sampling params with a hard 400, so a hardcoded default would make
    this builder unusable for exactly the models one would now choose. Same reasoning for top_p.

    `service_tier` enables the flex tier (~50% of standard price, higher latency, and it can return
    capacity errors). Long unattended
    agent runs are the ideal flex workload, so it is worth wiring; pair it with a generous
    `request_timeout` and `max_retries` because flex is slow and may transiently refuse.
    """
    from langchain_openai import ChatOpenAI
    api_key = os.environ.get(sub.get("api_key_env", "OPENAI_API_KEY"), "")

    kwargs: dict[str, Any] = {
        "model": sub.get("model", "gpt-4o"),
        "api_key": api_key or None,
    }
    # Only forward sampling params the config actually names (see docstring).
    for k in ("temperature", "top_p"):
        if k in sub and sub[k] is not None:
            kwargs[k] = sub[k]
    # Pass-through knobs, each only if present.
    for k in ("reasoning_effort", "max_tokens", "service_tier", "max_retries", "use_responses_api"):
        if sub.get(k) is not None:
            kwargs[k] = sub[k]
    if sub.get("request_timeout") is not None:
        kwargs["timeout"] = sub["request_timeout"]

    # `use_responses_api` is not cosmetic for a reasoning model: it is required for tool use.
    # On such a model, Chat Completions returns
    #   400 "Function tools with reasoning_effort are not supported for gpt-5.6-luna in
    #        /v1/chat/completions. To use function tools, use /v1/responses or set
    #        reasoning_effort to 'none'."
    # and the error fires even with reasoning_effort UNSET, because a reasoning model applies a
    # non-none default. Since this agent is almost entirely tool calls, Chat Completions would
    # fail on the first one. OpenAI's own reasoning guide also states plainly: "Reasoning models
    # work better with the Responses API ... you'll get improved model intelligence and
    # performance by using Responses."
    return ChatOpenAI(**kwargs)


def _build_anthropic(sub: dict[str, Any]) -> BaseChatModel:
    """Claude via the Anthropic API.

    THREE THINGS HERE RETURN A 400 IF YOU WRITE THEM THE WAY OLDER CODE DID.

    1. `temperature`, `top_p` and `top_k` are REMOVED on Claude Opus 5, Fable 5, Sonnet 5 and the
       4.7/4.8 family. Sending any of them is a 400, not a silently ignored field. So temperature is
       forwarded ONLY when the config explicitly sets it, which is how an older model such as
       Sonnet 4.5 can still be driven through this same builder. Leaving temperature unset for these
       models is required, not a style choice.
    2. `thinking={"type": "enabled", "budget_tokens": N}` is removed on the same models and returns
       a 400. Adaptive thinking replaces it, and on Opus 5 thinking is ON BY DEFAULT, so omitting
       the parameter still thinks. `display` defaults to "omitted", which leaves the thinking text
       empty. We ask for "summarized" because this project analyses the agent's reasoning after the
       fact and the summary costs nothing extra, thinking is billed identically either way.
    3. Assistant prefill is gone on these models. Nothing here prefills, but do not add it.

    EFFORT, not budget. `output_config.effort` is the replacement knob: low, medium, high, xhigh,
    max, defaulting to high. Anthropic recommends high or xhigh for long-horizon agentic work, so
    the config sets it explicitly rather than relying on the default.

    STREAMING IS ON. Opus 5 allows up to 128k output tokens but the SDK needs streaming for large
    values or the request hits the HTTP timeout. This agent routinely emits very long single
    generations, so streaming plus a large max_tokens is the correct pairing.

    THE KEY comes from the environment variable named by `api_key_env`, never from the config file
    and never printed. `.env` at the repo root is gitignored.
    """
    from langchain_anthropic import ChatAnthropic

    api_key = os.environ.get(sub.get("api_key_env", "ANTHROPIC_API_KEY"), "")

    kwargs: dict[str, Any] = {
        "model": sub.get("model", "claude-opus-5"),
        "anthropic_api_key": api_key or None,
        "max_tokens": int(sub.get("max_tokens", 64000)),
        "streaming": bool(sub.get("streaming", True)),
        "max_retries": int(sub.get("max_retries", 5)),
        "default_request_timeout": float(sub.get("request_timeout", 1800)),
    }

    # Adaptive thinking unless the config explicitly turns it off. `budget_tokens` is deliberately
    # not supported here: it is a 400 on every model this builder targets by default.
    if sub.get("thinking", True):
        kwargs["thinking"] = {
            "type": "adaptive",
            "display": sub.get("thinking_display", "summarized"),
        }

    effort = sub.get("reasoning_effort")
    if effort:
        kwargs["output_config"] = {"effort": str(effort)}

    # Only for pre-4.6 models, which still accept sampling parameters. Absent for Opus 5.
    if sub.get("temperature") is not None:
        kwargs["temperature"] = float(sub["temperature"])

    return ChatAnthropic(**kwargs)


def _build_groq(sub: dict[str, Any]) -> BaseChatModel:
    from langchain_groq import ChatGroq
    api_key = os.environ.get(sub.get("api_key_env", "GROQ_API_KEY"), "")
    return ChatGroq(
        model=sub.get("model", "llama-3.3-70b-versatile"),
        temperature=sub.get("temperature", 0.2),
        api_key=api_key or None,
    )


def _build_openai_compatible(sub: dict[str, Any]) -> BaseChatModel:
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=sub.get("model", "default"),
        base_url=sub.get("base_url", "http://localhost:8000/v1"),
        api_key=sub.get("api_key", "EMPTY"),
        temperature=sub.get("temperature", 0.2),
    )


def _build_vllm(sub: dict[str, Any]) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    kwargs = {
        "model": sub.get("model", "default"),
        "base_url": f"{sub.get('base_url', 'http://localhost:11436').rstrip('/')}/v1",
        "api_key": sub.get("api_key", "EMPTY"),
        "temperature": sub.get("temperature", 0.2),
    }

    if "top_p" in sub:
        kwargs["top_p"] = sub["top_p"]

    # vLLM-only sampling params (top_k, min_p, repetition_penalty, ...) are not
    # in the OpenAI schema. The OpenAI SDK rejects them as top-level kwargs but
    # forwards anything in `extra_body` straight into the request body, where
    # vLLM picks them up. Forwarded only when present, so a config
    # that omits them is unaffected.
    extra_body: dict[str, Any] = {}
    for _k in ("top_k", "min_p", "repetition_penalty"):
        if _k in sub:
            extra_body[_k] = sub[_k]

    # gpt-oss reasoning level: a real vLLM request field, not prose.
    # vLLM's chat API declares `reasoning_effort:
    #   Literal["none","minimal","low","medium","high","xhigh","max"]`
    # (entrypoints/openai/chat_completion/protocol.py) and threads it into
    # `get_system_message(reasoning_effort=...)` -> `with_reasoning_effort(...)`
    # (entrypoints/openai/parser/harmony_utils.py), so the official harmony library writes it into
    # the STRUCTURED slot of the system message that vLLM itself renders.
    # This matters: the harmony spec documents the level as a "Reasoning: high" line, which invites
    # prepending that text to our system prompt, but vLLM builds its own system message (model
    # identity, date, tools) and our text lands in the *instructions* section, NOT the reasoning
    # slot. Passing the field is therefore the correct mechanism and the prose prepend is not.
    # Harmony's DEFAULT is medium, so an unset value silently means medium.
    if sub.get("reasoning_effort"):
        extra_body["reasoning_effort"] = str(sub["reasoning_effort"]).strip().lower()

    if extra_body:
        kwargs["extra_body"] = extra_body

    return ChatOpenAI(**kwargs)


def _build_deepseek(sub: dict[str, Any]) -> BaseChatModel:
    """DeepSeek cloud API (OpenAI-compatible). Key comes from the env var named by
    `api_key_env` (default DEEPSEEK_API_KEY), never from config, so it stays out of git.

    THINKING is DEFAULT-OFF here (DeepSeek's own default is ON). Rationale for the agent:
      - Non-thinking honors `temperature` (DeepSeek recommends 0.0 for coding) and supports
        tool calling cleanly.
      - Thinking mode IGNORES temperature AND, when combined with tool calls, requires the
        assistant's `reasoning_content` to be echoed back every turn or the API returns 400,
        which LangChain does not reliably round-trip. Set `thinking: true` to opt in, but
        live-verify the tool loop first.
    Models: `deepseek-v4-pro` (default) or `deepseek-v4-flash`; just change `model`.
    """
    from langchain_openai import ChatOpenAI
    api_key = os.environ.get(sub.get("api_key_env", "DEEPSEEK_API_KEY"), "")
    kwargs: dict[str, Any] = {
        "model": sub.get("model", "deepseek-v4-pro"),
        "base_url": sub.get("base_url", "https://api.deepseek.com"),
        "api_key": api_key or None,
        "temperature": sub.get("temperature", 0.0),
    }
    if "max_tokens" in sub:
        kwargs["max_tokens"] = sub["max_tokens"]
    # Toggle DeepSeek thinking via extra_body (their default is "enabled"; we default OFF).
    thinking = "enabled" if sub.get("thinking", False) else "disabled"
    kwargs["extra_body"] = {"thinking": {"type": thinking}}
    return ChatOpenAI(**kwargs)
