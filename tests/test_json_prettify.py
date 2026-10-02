"""Contract tests for the post-run JSON normaliser in qme/tools/julia.py.

Why it exists: the agent's Julia writes data with JSON3.write, which emits one line.
deepagents' read_file is line-based, so on a single-line file every read returns the whole
file no matter what limit is passed, and a handful of such reads on a large data file can
blow the model's context window. Giving the file line structure makes a default 100-line
read return a slice instead.

The critical invariant is that values are untouched. Downstream analysis compares energies
against exact closed forms at precisions near 1e-16, so any rounding here would silently
destroy those results. These tests pin bit-exact round-tripping.

    python -m pytest tests/test_json_prettify.py
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qme.tools.julia as J  # noqa: E402


def _tmp_run_dir() -> Path:
    tmp = Path(tempfile.mkdtemp())
    J.RUN_DIR = tmp
    return tmp


def _payload() -> dict:
    # A realistic single-line DMRG payload: dense floats, full float64 repr.
    return {
        "energy": -8.999999999999982,
        "energy_per_site": -0.3750000000000003,
        "tiny": 9.637352644315594e-20,
        "sf_xx": [0.1 * i + 1e-17 for i in range(400)],
        "q_grid": [3.141592653589793 * i / 199 for i in range(200)],
        "L": 24, "boundary": "open",
    }


def test_prettify_adds_line_structure_and_preserves_values_bit_exactly():
    tmp = _tmp_run_dir()
    payload = _payload()
    big = tmp / "data.json"
    big.write_text(json.dumps(payload))          # one line, as JSON3.write emits
    before = big.read_text()
    assert before.count("\n") == 0 and len(before) > 8000, f"{len(before):,} B"

    J._prettify_json_outputs(["data.json"])
    after = big.read_text()

    assert after.count("\n") > 500, f"{after.count(chr(10)) + 1:,} lines"
    assert json.loads(after) == payload, "values must be bit-identical"
    for k in ("energy", "energy_per_site", "tiny"):
        assert repr(json.loads(after)[k]) == repr(payload[k]), \
            f"float repr changed for {k}: {json.loads(after)[k]!r}"
    assert repr(json.loads(after)["sf_xx"][3]) == repr(payload["sf_xx"][3]), \
        "array element repr changed"

    # idempotent: a second pass leaves the file as-is
    J._prettify_json_outputs(["data.json"])
    assert big.read_text() == after


def test_small_files_left_alone():
    # small files (params/config) must be left alone
    tmp = _tmp_run_dir()
    small = tmp / "params.json"
    small.write_text('{"Jy":0.5,"Jz":-0.25}')
    J._prettify_json_outputs(["params.json"])
    assert small.read_text() == '{"Jy":0.5,"Jz":-0.25}'


def test_non_json_and_missing_paths_are_noops():
    tmp = _tmp_run_dir()
    (tmp / "x.jl").write_text("x" * 20000)
    J._prettify_json_outputs(["x.jl", "does_not_exist.json", ""])   # nothing may raise
    assert (tmp / "x.jl").read_text() == "x" * 20000


def test_malformed_json_left_exactly_as_is():
    # malformed JSON must never be truncated or reformatted
    tmp = _tmp_run_dir()
    bad = tmp / "bad.json"
    bad.write_text("{not valid json" + "!" * 9000)
    raw = bad.read_text()
    J._prettify_json_outputs(["bad.json"])
    assert bad.read_text() == raw


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
