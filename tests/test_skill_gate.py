"""Contract tests for SkillGateMiddleware.

Each test pins one property that, if it broke, would either let a load-bearing skill go
unread or deadlock a run. The N1-ordering tests pin that `model-setup` must be read before
the code skill on a Julia write, so the operator convention is decided before the
Hamiltonian is coded.

    python -m pytest tests/test_skill_gate.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.agent import SkillGateMiddleware  # noqa: E402


def call(name, **args):
    return {"name": name, "args": args, "id": "x"}


def run(mw, tc):
    """Return 'passed' if the call reached the handler, 'blocked' if the gate stopped it."""
    out = {}

    def handler(_req):
        out["ok"] = True
        return "ran"

    class Req:
        tool_call = tc

        def override(self, **_k):
            return self

    mw.wrap_tool_call(Req(), handler)
    return "passed" if out.get("ok") else "blocked"


def test_gate_fires_once_then_releases():
    # The gate is a speed bump, not a wall.
    mw = SkillGateMiddleware("/tmp")
    first = run(mw, call("write_file", file_path="scripts/scan.jl"))
    second = run(mw, call("write_file", file_path="scripts/scan.jl"))
    assert (first, second) == ("blocked", "passed"), f"{first} -> {second}"


def test_n1_ordering_model_setup_precedes_itensor_dmrg():
    # Writing Julia needs model-setup first, then the code skill. Two gates, one trigger.
    mw = SkillGateMiddleware("/tmp")
    seq = [run(mw, call("write_file", file_path="scripts/hamiltonian.jl"))]
    run(mw, call("read_file", file_path="skills/model-setup/SKILL.md"))
    seq.append(run(mw, call("write_file", file_path="scripts/hamiltonian.jl")))
    run(mw, call("read_file", file_path="skills/itensor-dmrg/SKILL.md"))
    seq.append(run(mw, call("write_file", file_path="scripts/hamiltonian.jl")))
    assert seq == ["blocked", "blocked", "passed"], str(seq)


def test_skill_for_hands_over_from_model_setup_to_code_skills():
    mw = SkillGateMiddleware("/tmp")
    assert mw._skill_for("write_file", {"file_path": "scripts/scan.jl"}) == "model-setup", \
        "model-setup must claim the .jl trigger while unread"
    mw._read.add("model-setup")
    assert mw._skill_for("write_file", {"file_path": "scripts/scan.jl"}) == "itensor-dmrg", \
        "after model-setup is read, the .jl trigger belongs to itensor-dmrg"
    assert mw._skill_for("write_file", {"file_path": "scripts/ed_x.jl"}) == "ed-validation", \
        "an ED script hands over to ed-validation instead"


def test_reading_skills_up_front_means_never_blocked():
    mw = SkillGateMiddleware("/tmp")
    run(mw, call("read_file", file_path="skills/model-setup/SKILL.md"))
    run(mw, call("read_file", file_path="skills/itensor-dmrg/SKILL.md"))
    assert run(mw, call("write_file", file_path="scripts/scan.jl")) == "passed"


def test_gate_state_survives_summarisation():
    # The gate must track reads in its own state, not by scanning messages. Scanning would
    # lose the read_file once the transcript is compacted, and the gate would re-fire mid-run.
    mw = SkillGateMiddleware("/tmp")
    run(mw, call("read_file", file_path="skills/model-setup/SKILL.md"))
    assert run(mw, call("run_julia_batch", argv_list=["a,b"])) == "passed"


def test_cheap_persistent_session_probe_ungated():
    mw = SkillGateMiddleware("/tmp")
    assert run(mw, call("run_julia", fresh=False)) == "passed"


def test_non_julia_writes_ungated():
    mw = SkillGateMiddleware("/tmp")
    assert mw._skill_for("write_file", {"file_path": "note/research_note.md"}) is None


def test_finish_gated_on_reporting_checklist():
    mw = SkillGateMiddleware("/tmp")
    assert run(mw, call("finish", reason="done")) == "blocked"


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
