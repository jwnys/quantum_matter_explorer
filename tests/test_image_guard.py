"""Contract tests for the image-read guard.

Pins: (1) `is_image_path` recognises exactly the extensions deepagents multimodal-encodes
(case-insensitive) and nothing else; (2) the middleware stubs a `read_file` on an image
without calling the real tool, but passes every other call straight through, so a
vision-off server never receives an image and normal reads are untouched; (3) the guard
and the overflow classifier reach every subagent deepagents builds, including the
auto-created `general-purpose` one.

    python -m pytest tests/test_image_guard.py
"""
import sys
from pathlib import Path

import pytest
from langchain_core.messages import ToolMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qme.image_guard import ImageReadGuard, is_image_path  # noqa: E402

SRC_AGENT = Path(__file__).resolve().parents[1] / "qme" / "agent.py"


def call(name, **args):
    return {"name": name, "args": args, "id": "tc1"}


def run(mw, tc):
    """('stub', ToolMessage) if the guard short-circuited; ('passed', handler_ret) if it called handler."""
    called = {}

    def handler(_req):
        called["ok"] = True
        return "HANDLER-RAN"

    class Req:
        tool_call = tc

        def override(self, **_k):
            return self

    out = mw.wrap_tool_call(Req(), handler)
    return ("passed", out) if called.get("ok") else ("stub", out)


# Predicate: exactly the extensions deepagents multimodal-encodes.

@pytest.mark.parametrize("path", [
    "plots/x.png", "a/b/c.PNG", "x.jpg", "x.jpeg", "x.webp", "x.gif", "x.heic", "X.HEIF",
])
def test_is_image_path_true(path):
    assert is_image_path(path)


@pytest.mark.parametrize("path", [
    "data/x.json", "note/research_note.md", "scripts/scan.jl", "x.txt", "x.csv",
    "x.png.json", "plots/", "x.svg",   # note: .svg is not in deepagents' image set
])
def test_is_image_path_false(path):
    assert not is_image_path(path)


# Middleware behaviour.

def test_read_file_on_image_is_stubbed_without_calling_handler():
    kind, out = run(ImageReadGuard(), call("read_file", file_path="plots/survey_heatmaps.png"))
    assert kind == "stub"
    assert isinstance(out, ToolMessage) and out.status == "success"
    assert out.name == "read_file"
    assert "REFUSED" in out.content
    assert "Do NOT call read_file on image files" in out.content
    assert "data/*.json" in out.content


def test_read_file_on_non_image_passes_through():
    kind, out = run(ImageReadGuard(), call("read_file", file_path="data/fss_L16.json"))
    assert (kind, out) == ("passed", "HANDLER-RAN")


def test_non_read_file_tool_on_image_path_passes_through():
    kind, _ = run(ImageReadGuard(), call("write_file", file_path="plots/x.png", content="..."))
    assert kind == "passed"


def test_unrelated_tool_passes_through():
    kind, _ = run(ImageReadGuard(), call("run_julia", fresh=False))
    assert kind == "passed"


# Regression: both safety middlewares must reach every subagent deepagents builds.
# deepagents auto-creates a `general-purpose` subagent with its own middleware list, and a
# guard attached only to the main agent (or only to declared subagents) does not reach it.
# A subagent reading an image on a language-only server, or overflowing its own context,
# then kills the run. Assert the property that matters: every subagent carries both guards.

def _registered_profiles():
    from langchain_openai import ChatOpenAI            # noqa: PLC0415
    from qme.agent import _register_safety_profile     # noqa: PLC0415

    probe = ChatOpenAI(model="gpt-4o-mini", api_key="dummy", base_url="http://localhost:1")
    return probe, _register_safety_profile


def test_profile_registered_for_vision_capable_model():
    # The overflow classifier is not vision-gated: an overflow can happen on any model. So a
    # vision-capable config still registers a profile, just without the image guard.
    probe, register = _registered_profiles()
    assert register(probe, {"llm": {"vision": True}}) is True


def test_profile_registered_when_vision_unset():
    probe, register = _registered_profiles()
    assert register(probe, {"llm": {}}) is True


def _build_and_spy_subagents():
    """Build a deep agent with the safety profile registered and record, per subagent,
    the middleware class names deepagents attaches to it."""
    import deepagents.middleware.subagents as _sub     # noqa: PLC0415
    from deepagents import create_deep_agent           # noqa: PLC0415

    probe, register = _registered_profiles()
    register(probe, {"llm": {}})

    seen: dict = {}
    _orig = _sub.create_sub_agent

    def _spy(spec, *a, **k):
        seen[spec["name"]] = [type(m).__name__ for m in spec.get("middleware", [])]
        return _orig(spec, *a, **k)

    _sub.create_sub_agent = _spy
    try:
        create_deep_agent(model=probe, tools=[],
                          subagents=[{"name": "declared", "description": "d",
                                      "system_prompt": "s", "tools": []}])
    finally:
        _sub.create_sub_agent = _orig
    return seen


def test_every_subagent_carries_both_guards_and_library_middleware():
    seen = _build_and_spy_subagents()
    assert "general-purpose" in seen, str(list(seen))
    for name, mws in seen.items():
        assert "ImageReadGuard" in mws, f"ImageReadGuard missing from subagent {name!r}: {mws}"
        assert "ContextOverflowClassifier" in mws, \
            f"ContextOverflowClassifier missing from subagent {name!r}: {mws}"
        assert "FilesystemMiddleware" in mws, \
            f"library middleware not preserved for {name!r}: {mws}"


# The guard must not also be appended per-agent: duplicate instances are fatal.

def test_no_manual_per_agent_middleware_appends_remain():
    src_all = SRC_AGENT.read_text()
    assert "middleware.append(ImageReadGuard())" not in src_all
    assert "middleware.append(ContextOverflowClassifier())" not in src_all
    assert "mw.append(ContextOverflowClassifier())" not in src_all


def test_subagent_middleware_builder_still_present():
    # The safety middleware must flow through the dedicated subagent builder. If either
    # construct is renamed or removed, this file's regression coverage needs revisiting.
    src = SRC_AGENT.read_text()
    assert "def _subagent_safety_mw" in src
    assert "subagents: list[dict] = []" in src
    assert src.index("def _subagent_safety_mw") < src.index("subagents: list[dict] = []")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
