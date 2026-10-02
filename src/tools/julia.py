"""
src/tools/julia.py
The `run_julia` tool, the project's DMRG instrument (ITensorMPS via Julia),
with two hard guards (objective, cheap, high cost if violated):

  1. Refuse a run whose parameter JSON still contains a placeholder coupling
     ("variable", "scan", "", ...). These silently collapse to 0.0 in Julia's
     `get(params, "J2", 0.0)` idiom and poison the whole scan, so they are
     caught at the tool boundary instead of producing wrong physics.
  2. Auto-report DMRG convergence (truncation error, total Sz, final energy)
     parsed from stdout, so the agent and the physics-critic can never proceed
     unaware of non-convergence. Annotates, never blocks: partial convergence
     is sometimes usable, and that judgment stays soft.

The run dir and the Julia executable/project/library paths come from the
`QME_*` env vars set by main.py before the tools are imported.

Two modes:
  fresh=False   persistent REPL (state survives across calls); quick probes.
  fresh=True    new subprocess per call; full DMRG scripts; argv -> ARGS[1..].

The result is a structured text block whose first line `parse_result_header`
can re-parse (status / wall / returncode / fresh).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from .sandbox import RUN_DIR
from ..util.param_utils import is_numeric, _PLACEHOLDER_TOKENS


_scratch: Any = None         # lazily instantiated JuliaScratch (persistent mode)
_init_error: str | None = None


def _ensure_scratch():
    """Construct the persistent JuliaScratch on first use; cache the error
    if it fails. Only used by the fresh=False path."""
    global _scratch, _init_error
    if _scratch is not None or _init_error is not None:
        return
    try:
        from .julia_scratch import JuliaScratch
        julia_cfg = {
            "executable": os.environ.get("QME_JULIA_EXE", "julia"),
            "project_dir": os.environ.get("QME_JULIA_PROJECT", ""),
            "launch_timeout_seconds": int(os.environ.get("QME_JULIA_LAUNCH_TIMEOUT", "30")),
        }
        if RUN_DIR is not None:
            os.chdir(str(RUN_DIR))
        _scratch = JuliaScratch(julia_cfg, launch_timeout_s=julia_cfg["launch_timeout_seconds"])
    except Exception as exc:
        _init_error = f"(run_julia init failed: {exc})"


def _fmt_result(*, status: str, wall_s: float, returncode: int | None,
                fresh: bool, stdout: str, stderr: str,
                output_file: str | None = None) -> str:
    """Format a uniform structured result string for both modes.

    `output_file` is the point's data JSON when there is one. A fresh run's last argv item is
    that path by convention, and a REPL probe has none.
    """
    rc_field = f"returncode={returncode}, " if returncode is not None else ""
    head = (
        f"(run_julia status={status}, wall={wall_s:.1f}s, "
        f"{rc_field}fresh={'True' if fresh else 'False'})"
    )
    parts = [head]
    if status == "TIMEOUT":
        parts.append(
            "HINT: the run exceeded the timeout. DMRG is slow (minutes): pass a LARGER `timeout_s`, "
            "OR reduce bond dimension χ / system size L. Do NOT retry at the same settings (that loops)."
        )
    # Guard 2: surface convergence up front when this looks like a DMRG run.
    conv = _convergence_report(stdout, output_file)
    if conv:
        parts.append(conv)
    stdout = (stdout or "").strip()
    stderr = (stderr or "").strip()
    if stdout:
        parts.append(f"stdout:\n{stdout}")
    if stderr:
        parts.append(f"stderr:\n{stderr}")
    if not stdout and not stderr:
        parts.append("(no output)")
    return "\n".join(parts)


# Structured header regex: callers can pull status/returncode/wall back out.
_HEADER_RE = re.compile(
    r"\(run_julia status=(?P<status>\w+),\s*wall=(?P<wall>[\d.]+)s,"
    r"(?:\s*returncode=(?P<rc>-?\d+),)?\s*fresh=(?P<fresh>True|False)\)"
)


def parse_result_header(text: str) -> dict | None:
    """Extract the structured fields from a run_julia result string.
    Returns {status, wall_s, returncode, fresh} or None if no header found."""
    m = _HEADER_RE.search(text or "")
    if not m:
        return None
    return {
        "status":     m.group("status"),
        "wall_s":     float(m.group("wall")),
        "returncode": int(m.group("rc")) if m.group("rc") is not None else None,
        "fresh":      m.group("fresh") == "True",
    }


# --- Guard 1: refuse placeholder couplings ---

def _check_placeholder_params(argv: list[str]) -> str | None:
    """Scan any *.json file in argv for placeholder coupling values. Returns a
    refusal message if a placeholder is found, else None.

    A value is a placeholder if its lowercased string is one of the known
    scan-placeholder tokens ("variable", "scan", "", ...). Genuine non-numeric
    values (e.g. "boundary":"open") are NOT placeholders and pass."""
    for item in argv:
        p = (RUN_DIR / item.lstrip("/")) if (RUN_DIR and not Path(item).is_absolute()) else Path(item)
        try:
            if not (p.suffix == ".json" and p.is_file()):
                continue
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        bad = {
            k: v for k, v in data.items()
            if not is_numeric(v) and str(v).strip().lower() in _PLACEHOLDER_TOKENS
        }
        if bad:
            return (
                f"(run_julia BLOCKED: placeholder coupling(s) in {p.name}: {bad}. "
                f"Every coupling must be a CONCRETE NUMBER before a DMRG run "
                f"(a placeholder silently becomes 0.0 in Julia and poisons the scan). "
                f"Write the numeric value into the params JSON and retry.)"
            )
    return None


# --- Guard 2: convergence auto-report ---

# Gap between a label and its number: separators only (`:`, `=`, spaces, `>`, ...).
# It must not swallow a leading minus sign or the number itself.
_GAP = r"[\s:=>()\[\]]{0,6}"
_NUM = r"(-?[\d.]+(?:[eE][-+]?\d+)?)"
_CONV_PATTERNS = {
    "trunc_err":    re.compile(rf"(?:trunc[_ ]?err(?:or)?|truncation[_ ]?error|maxerr){_GAP}{_NUM}", re.I),
    "total_Sz":     re.compile(rf"(?:total[_ ]?Sz|TOTAL_SZ){_GAP}{_NUM}", re.I),
    "final_energy": re.compile(rf"(?:final[_ ]?energy|FINAL_ENERGY|energy[_ ]?per[_ ]?site|ENERGY_PER_SITE){_GAP}{_NUM}", re.I),
}


def _dump_point_json(output_file: str | None, max_keys: int = 48) -> str | None:
    """List the numbers the point stored, under the names its own script gave them.

    Deliberately dumb, and that is the design. The script names its own keys and the
    names are not a contract, so any attempt to guess which key holds the sweep history
    (and flag its convergence) misfires on keys that happen to look similar. Nothing
    here is interpreted: no thresholds, no flags. Scalars are printed as they are,
    numeric arrays as their length with the first and last entries, and whoever reads
    it wrote the script that chose the names.
    """
    if not output_file:
        return None
    path = (RUN_DIR / output_file.lstrip("/")) if (RUN_DIR and not Path(output_file).is_absolute()) \
        else Path(output_file)
    try:
        d = json.loads(path.read_text())
    except Exception:
        return None
    if not isinstance(d, dict):
        return None

    lines: list[str] = []

    def num(x):
        return f"{x:.10g}" if isinstance(x, float) else str(x)

    def walk(o, prefix=""):
        if len(lines) >= max_keys or not isinstance(o, dict):
            return
        for k, v in o.items():
            if len(lines) >= max_keys:
                lines.append("… (truncated; read the file for the rest)")
                return
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                lines.append(f"{prefix}{k} = {num(v)}")
            elif isinstance(v, list) and v and all(isinstance(x, (int, float)) for x in v):
                # First and the last two. Two so the reader can difference them, which for a
                # sweep history is the convergence step and for a spatial profile is just the
                # last two sites. Which of those it is, is not the harness's call to make.
                if len(v) == 1:
                    lines.append(f"{prefix}{k}[1]: {num(v[0])}")
                else:
                    lines.append(f"{prefix}{k}[{len(v)}]: first {num(v[0])}"
                                 f"   last two {num(v[-2])}, {num(v[-1])}")
            elif isinstance(v, dict):
                walk(v, prefix + k + ".")

    walk(d)
    if not lines:
        return None
    return f"STORED IN {output_file}:\n  " + "\n  ".join(lines)


def _convergence_report(stdout: str, output_file: str | None = None) -> str | None:
    """Best-effort: pull convergence scalars from stdout and emit a compact
    `CONVERGENCE:` line. Heuristic: relies on the script printing the standard
    diagnostics; if none are found and the run looks DMRG-ish, nudge the agent
    to print them."""
    dump = _dump_point_json(output_file)
    if not stdout:
        return dump
    found = {}
    for name, pat in _CONV_PATTERNS.items():
        hits = pat.findall(stdout)
        if hits:
            found[name] = hits[-1]  # last occurrence = final/converged value
    looks_dmrg = bool(re.search(r"dmrg|sweep|maxlinkdim|bond\s*dim", stdout, re.I))
    if not found:
        if dump:
            return dump
        if looks_dmrg:
            return ("CONVERGENCE: markers not found. Print TRUNC_ERR, total Sz and the "
                    "per-sweep / final energy so convergence can be checked.")
        return None
    bits = []
    te = found.get("trunc_err")
    if te is not None:
        # No [OK]/[HIGH] verdict here: that would mean comparing a max-over-sweeps
        # truncation error against a fixed threshold with no knowledge of the cutoff
        # the point requested, and a flag that is almost always on carries no
        # information and teaches the reader to skip the whole line.
        bits.append(f"trunc_err={te}")
    if "total_Sz" in found:
        bits.append(f"total_Sz={found['total_Sz']}")
    if "final_energy" in found:
        bits.append(f"final_energy={found['final_energy']}")
    # Do not ask for per-sweep monotonicity: the canonical sweep schedule enables
    # `noise!`, under which the energy is not variational sweep-to-sweep, so that check
    # fires on healthy runs and trains the agent to ignore the whole report.
    line = ("CONVERGENCE: " + ", ".join(bits)
            + " (check the last-sweep energy change and that total Sz is the sector you intended)")
    return line + "\n" + dump if dump else line

# --- REPL mode (interactive sanity checks / probes) ---

def _run_in_repl(code: str, timeout_s: int) -> str:
    _ensure_scratch()
    if _scratch is None:
        return _init_error or "(run_julia not available)"
    result = _scratch.evaluate(code, timeout_s=timeout_s)
    status = "OK" if result.ok else ("TIMEOUT" if result.timed_out else "ERROR")
    return _fmt_result(
        status=status, wall_s=result.wall_time_s,
        returncode=None, fresh=False, stdout=result.stdout, stderr=result.stderr,
    )


# --- Fresh-subprocess mode (full DMRG scripts) ---

def _resolve_script_path(code: str) -> Path | None:
    """If `code` names an existing .jl file (run-dir-relative or absolute),
    return the resolved path; else None (treat `code` as inline source)."""
    if len(code) >= 4096 or "\n" in code:
        return None
    candidates = []
    if RUN_DIR is not None and not Path(code).is_absolute():
        candidates.append((RUN_DIR / code.lstrip("/")))
    candidates.append(Path(code).expanduser())
    for c in candidates:
        try:
            if c.is_file():
                return c.resolve()
        except OSError:
            continue
    return None


def _exec_fresh(code: str, timeout_s: int,
                argv: list[str] | None = None) -> dict:
    """Spawn a NEW `julia ...` subprocess per call and return STRUCTURED fields
    `{status, wall_s, returncode, stdout, stderr}`. Shared by the single `run_julia`
    (fresh=True) path and `run_julia_batch`. `code` is either an on-disk `.jl` path
    (run-dir-relative or absolute → `include`'d) or inline source (written to a temp
    .jl). argv items become `ARGS[1..]` inside Julia.

    Guard refusals (placeholder params, out-of-sandbox path, julia not found) come
    back as `status=ERROR` with the message in `stderr`. Output is decoded
    utf-8/errors=replace so odd bytes from Julia can never raise mid-capture."""
    argv = argv or []

    def _err(msg: str) -> dict:
        return {"status": "ERROR", "wall_s": 0.0, "returncode": None,
                "stdout": "", "stderr": msg}

    # Guard 1: no placeholder couplings in any params JSON passed via argv.
    blocked = _check_placeholder_params(argv)
    if blocked:
        return _err(blocked)

    julia_exe = os.environ.get("QME_JULIA_EXE", "julia")
    project = os.environ.get("QME_JULIA_PROJECT", "") or None

    cmd: list[str] = [julia_exe, "--startup-file=no", "--quiet"]
    if project:
        cmd.append(f"--project={project}")
    cmd.append(f"--threads={os.environ.get('JULIA_NUM_THREADS', '8')}")

    script_path = _resolve_script_path(code)
    tmp_path: Path | None = None
    if script_path is not None:
        # Sandbox: a fresh-mode path must live inside RUN_DIR (the model could
        # otherwise point at any .jl on disk). Inline code is safe (temp file).
        if RUN_DIR is not None:
            try:
                script_path.relative_to(RUN_DIR)
            except ValueError:
                return _err(
                    f"(run_julia [fresh] blocked: path {script_path} is outside the run "
                    f"folder {RUN_DIR}. Use an inline snippet or a path written inside "
                    f"the run dir via write_file.)"
                )
        cmd.append(str(script_path))
        cmd.extend(argv)
    else:
        # Write the inline temp .jl inside run_dir/scripts/, not /tmp. Julia's `include("X")`
        # resolves relative to the including file's own directory, so an inline snippet that does
        # `include("hamiltonian.jl")` must sit next to the shared scripts; otherwise it looks for
        # /tmp/hamiltonian.jl and fails. (cwd stays run_dir, so `data/...`/ARGS paths are unaffected.)
        tmp_dir = (RUN_DIR / "scripts") if RUN_DIR is not None else None
        if tmp_dir is not None:
            tmp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jl", delete=False, encoding="utf-8",
            dir=(str(tmp_dir) if tmp_dir is not None else None),
        ) as tmp:
            tmp.write(code)
            tmp_path = Path(tmp.name)
        cmd.append(str(tmp_path))
        cmd.extend(argv)

    cwd = str(RUN_DIR) if RUN_DIR else None
    t0 = time.monotonic()
    timed_out = False
    rc = -1
    stdout = ""
    stderr = ""
    try:
        # utf-8/errors=replace: Julia/ITensor may emit non-ASCII (ΔE, σ, →) or odd
        # bytes; strict decoding would raise UnicodeDecodeError and kill the capture.
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout_s, cwd=cwd,
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        rc = proc.returncode
    except subprocess.TimeoutExpired as e:
        stdout = (e.stdout if isinstance(e.stdout, str) else "") or ""
        stderr = ((e.stderr if isinstance(e.stderr, str) else "") or ""
                  + f"\n(timeout after {timeout_s}s)")
        timed_out = True
    except FileNotFoundError as exc:
        return _err(f"(run_julia [fresh]: julia executable not found: {exc})")
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass

    wall = time.monotonic() - t0
    status = "OK" if (rc == 0 and not timed_out) else ("TIMEOUT" if timed_out else "ERROR")
    # Give any large single-line JSON this run just wrote some line structure, so that a later
    # read_file(limit=N) returns a SLICE instead of the whole file. See _prettify_json_outputs.
    # Runs on every outcome, not just OK: a timed-out point can still have written its data.
    _prettify_json_outputs(argv)
    return {"status": status, "wall_s": wall, "returncode": rc,
            "stdout": stdout, "stderr": stderr}


# --- Post-run: make written JSON readable in slices ---
#
# The agent's Julia writes data with `JSON3.write`, which emits one line. deepagents'
# read_file is line-based, so on a single-line file every read returns the whole thing
# regardless of the limit argument, and a handful of such reads can exhaust a reviewer
# subagent's context window. The fix is applied where we have control: give the file
# line structure, so a default 100-line read returns a slice instead of the whole file.
#
# Values are not touched. No rounding, no key changes, no reordering: json.load ->
# json.dump with indent only. Python's float repr round-trips float64 bit-exactly, so
# energies stay comparable at the 1e-16 level. Rounding here would silently destroy
# that comparability, which is why it is deliberately absent.
_PRETTY_MIN_BYTES = 8_000     # leave small params/config files alone
_PRETTY_MAX_LINES = 4         # already line-structured? then read_file's limit already works

def _prettify_json_outputs(argv: "list[str]") -> None:
    """Re-dump any large single-line *.json in argv with newlines. Best-effort and idempotent:
    any failure leaves the file exactly as Julia wrote it."""
    for item in argv or []:
        try:
            p = (RUN_DIR / item.lstrip("/")) if (RUN_DIR and not Path(item).is_absolute()) else Path(item)
            if p.suffix != ".json" or not p.is_file():
                continue
            raw = p.read_text(encoding="utf-8")
            if len(raw) < _PRETTY_MIN_BYTES or raw.count("\n") >= _PRETTY_MAX_LINES:
                continue
            p.write_text(json.dumps(json.loads(raw), indent=1), encoding="utf-8")
        except Exception:
            continue      # never let cosmetics fail a DMRG run


def _run_in_fresh_subprocess(code: str, timeout_s: int,
                             argv: list[str] | None = None) -> str:
    """Single fresh run → the structured text block (single-call output unchanged)."""
    argv = argv or []
    d = _exec_fresh(code, timeout_s, argv)
    return _fmt_result(
        status=d["status"], wall_s=d["wall_s"], returncode=d["returncode"],
        fresh=True, stdout=d["stdout"], stderr=d["stderr"],
        output_file=argv[-1] if argv else None,
    )


# --- Public entry: internal callable + the LangChain tool ---

def _configured_timeout() -> int:
    """The per-call DMRG budget actually in force, for the tool descriptions below.

    Read at import: main.py sets QME_JULIA_RUN_TIMEOUT before the tools are imported, so this
    is the real value rather than a hardcoded guess that goes stale when the config changes.
    Stating it matters: with no number in the docstring an agent has no way to learn its
    budget except by exceeding it, and it then tends to guess low and lose exactly the
    largest system sizes the study needed.
    """
    try:
        return int(os.environ.get("QME_JULIA_RUN_TIMEOUT", "600"))
    except ValueError:
        return 600


_RUN_TIMEOUT_S = _configured_timeout()


def _configured_parallel() -> int:
    """How many batch points run at once, for the tool description below.

    Same failure mode as the timeout: `max_parallel` is a default, not a ceiling (see the
    `cap = ...` line in run_julia_batch_impl), so an explicit smaller value wins over the
    configured one and the config cannot pull it back up. With the number absent from the
    description an agent has no way to learn the capacity, and it then tends to guess low
    and run its survey far narrower than the machine allows."""
    try:
        return int(os.environ.get("QME_JULIA_BATCH_MAX_PARALLEL", "8"))
    except ValueError:
        return 8


_BATCH_MAX_PARALLEL = _configured_parallel()


def _resolve_timeout(timeout_s: int) -> int:
    """`timeout_s <= 0` means use the configured run timeout (`QME_JULIA_RUN_TIMEOUT`,
    default 600 s). A real DMRG takes minutes, so the default must be generous: a
    seconds-scale default would silently time out every full run."""
    if timeout_s and timeout_s > 0:
        return int(timeout_s)
    try:
        return int(os.environ.get("QME_JULIA_RUN_TIMEOUT", "600"))
    except ValueError:
        return 600


def run_julia_impl(code: str, timeout_s: int = 0, fresh: bool = False,
                   argv: list[str] | str | None = None) -> str:
    """Internal callable (also usable from non-LLM code). See the tool docstring.
    `timeout_s <= 0` uses the configured run timeout (`QME_JULIA_RUN_TIMEOUT`, default 600)."""
    timeout_s = _resolve_timeout(timeout_s)
    if isinstance(argv, str):
        argv = [a.strip() for a in argv.split(",") if a.strip()]
    if fresh:
        return _run_in_fresh_subprocess(code, timeout_s, argv=argv or [])
    return _run_in_repl(code, timeout_s)


@tool(parse_docstring=True)
def run_julia(code: str, timeout_s: int = 0, fresh: bool = False,
              argv: str = "") -> str:
    """Run Julia code for DMRG / ITensorMPS work. Returns a structured result with a convergence summary.

    Two modes:
      - fresh=False (default): a PERSISTENT REPL. State (variables, loaded
        packages) survives across calls. Use to PROBE (`?dmrg`, `siteinds(...)`,
        a kwarg check, a 2-site sanity DMRG) before committing to a full script.
      - fresh=True: a NEW subprocess per call. Use for full DMRG runs. `code` may
        be inline Julia OR the path to a `.jl` file you wrote (e.g.
        "scripts/exp_01.jl", run-dir-relative). `argv` items become Julia's
        `ARGS[1..]`; pass a params file path, e.g. argv="params/p01.json".

    Guards: a run is REFUSED if a params JSON in argv still holds a placeholder
    coupling (e.g. "variable"); the result always includes a CONVERGENCE line
    (trunc_err / total Sz / final energy) when the run looks like DMRG.

    Args:
        code: Inline Julia source, or (fresh=True) a run-dir-relative path to a .jl file.
        timeout_s: Max wall-clock seconds. 0 (default) uses the configured run timeout, which on
            THIS run is {_RUN_TIMEOUT_S}s. Pass 0 and you get all of it. Do NOT pass a smaller
            number to be safe: a full DMRG needs MINUTES, and self-limiting below the configured
            budget is how a run loses exactly the largest sizes it was launched to reach. Use a
            small value only for a deliberate quick probe. A TIMEOUT means raise timeout_s (up to
            {_RUN_TIMEOUT_S}s) OR reduce χ/L. Never retry the same settings.
        fresh: False = persistent REPL probe; True = new subprocess for a full run.
        argv: Comma-separated strings passed as Julia ARGS (fresh mode), e.g. "params/p01.json".
    """
    return run_julia_impl(code, timeout_s=timeout_s, fresh=fresh, argv=argv or None)


# --- Batch mode: many points as concurrent fresh subprocesses ---

_TAIL_CHARS = 4000


def _tail(s: str, n: int = _TAIL_CHARS) -> str:
    """Keep the last n chars (the tail holds the final sweeps / energy / error)."""
    s = s or ""
    return s if len(s) <= n else "…(head truncated; full output in log_file)…\n" + s[-n:]


def _point_id(items: list[str], index: int) -> str:
    """Stable per-point id = the output file's stem (last argv item), else run_NN."""
    if items:
        stem = Path(items[-1]).stem
        if stem:
            return stem
    return f"run_{index:02d}"


def _write_point_log(pid: str, combo: str, d: dict) -> str | None:
    """Write the full per-point block to run_dir/logs/julia/<id>.log (only called
    when output is truncated or the point failed). Returns the run-dir-relative
    path, or None if it can't be written. Thread-safe: unique path per point."""
    if RUN_DIR is None:
        return None
    log_dir = RUN_DIR / "logs" / "julia"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        _items = [a.strip() for a in (combo or "").split(",") if a.strip()]
        block = _fmt_result(
            status=d["status"], wall_s=d.get("wall_s", 0.0), returncode=d.get("returncode"),
            fresh=True, stdout=d.get("stdout", ""), stderr=d.get("stderr", ""),
            output_file=_items[-1] if _items else None,
        )
        (log_dir / f"{pid}.log").write_text(f"# point {pid}  argv={combo}\n{block}\n",
                                            encoding="utf-8")
    except OSError:
        return None
    return f"logs/julia/{pid}.log"


def _build_entry(index: int, combo: str, items: list[str], d: dict) -> dict:
    """Turn one point's structured result into a manifest entry."""
    pid = _point_id(items, index)
    stdout = d.get("stdout", "") or ""
    stderr = d.get("stderr", "") or ""
    # Write a full log ONLY when it adds value: failed/timed-out OR output truncated.
    log_file = None
    if d["status"] != "OK" or len(stdout) > _TAIL_CHARS or len(stderr) > _TAIL_CHARS:
        log_file = _write_point_log(pid, combo, d)
    return {
        "id": pid,
        "argv": combo,
        "output_file": items[-1] if items else None,
        "status": d["status"],
        "wall_s": round(d.get("wall_s", 0.0), 1),
        "returncode": d.get("returncode"),
        "convergence": _convergence_report(stdout, items[-1] if items else None),
        "stdout": _tail(stdout),
        "stderr": _tail(stderr),
        "log_file": log_file,
    }


def _parse_argv_list(s: str) -> list[str]:
    """Accept either a JSON array of strings or a newline/semicolon-separated list.
    NOT comma-split: commas separate the args WITHIN one point."""
    s = s.strip()
    if s.startswith("["):
        try:
            v = json.loads(s)
            if isinstance(v, list):
                return [str(x) for x in v]
        except Exception:
            pass
    return [p.strip() for p in re.split(r"[\n;]+", s) if p.strip()]


def run_julia_batch_impl(code: str, argv_list: list[str] | str,
                         timeout_s: int = 0, max_parallel: int = 0) -> str:
    """Run ONE script over MANY argv combos as CONCURRENT fresh subprocesses.
    Returns a JSON manifest (one entry per point). See the tool docstring."""
    timeout_s = _resolve_timeout(timeout_s)
    if isinstance(argv_list, str):
        argv_list = _parse_argv_list(argv_list)
    combos = [a for a in (argv_list or []) if a and str(a).strip()]
    if not combos:
        return json.dumps({"tool": "run_julia_batch",
                           "error": "argv_list is empty: pass one 'params,output' string per point."})

    cap = max_parallel if (max_parallel and max_parallel > 0) else \
        int(os.environ.get("QME_JULIA_BATCH_MAX_PARALLEL", "8"))
    cap = max(1, min(cap, len(combos)))

    def _one(index: int, combo: str) -> dict:
        items = [x.strip() for x in combo.split(",") if x.strip()]
        try:
            d = _exec_fresh(code, timeout_s, items)
        except Exception as exc:  # never let one point kill the batch
            d = {"status": "ERROR", "wall_s": 0.0, "returncode": None,
                 "stdout": "", "stderr": f"(batch worker crashed: {exc})"}
        return _build_entry(index, combo, items, d)

    results: list[dict | None] = [None] * len(combos)
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=cap) as ex:
        futs = {ex.submit(_one, i, c): i for i, c in enumerate(combos)}
        for fut in as_completed(futs):
            results[futs[fut]] = fut.result()
    wall = time.monotonic() - t0

    runs = [r for r in results if r is not None]
    manifest = {
        "tool": "run_julia_batch",
        "summary": {
            "n": len(runs),
            "ok": sum(1 for r in runs if r["status"] == "OK"),
            "error": sum(1 for r in runs if r["status"] == "ERROR"),
            "timeout": sum(1 for r in runs if r["status"] == "TIMEOUT"),
            "wall_s": round(wall, 1),
            "parallel": cap,
        },
        "runs": runs,
    }
    return json.dumps(manifest, indent=2, ensure_ascii=False)


@tool(parse_docstring=True)
def run_julia_batch(code: str, argv_list: list[str], timeout_s: int = 0,
                    max_parallel: int = 0) -> str:
    """Run ONE Julia script over MANY parameter sets IN PARALLEL: the fast way to do a survey / scan.

    Each list entry runs as its OWN fresh subprocess (fully isolated: one crash/timeout = ONE failed
    point, the rest still finish), several at a time across cores. Use this INSTEAD OF many separate
    `run_julia(fresh=True)` calls whenever you have a SERIES of independent DMRG points (a phase-diagram
    survey, a finite-size scan, …). One call replaces the whole loop.

    Returns a JSON manifest: {"summary": {n, ok, error, timeout, wall_s, parallel}, "runs": [ {id, argv,
    output_file, status, wall_s, returncode, convergence, stdout, stderr, log_file}, … ]}. Walk the "runs"
    list and process each entry exactly as you would a single `run_julia` result; read each point's
    `output_file` (the data/*.json it wrote) for the numbers. Failed points have status ERROR/TIMEOUT and
    a populated `log_file` with the full output.

    Args:
        code: Run-dir-relative path to the .jl script run for EVERY point, e.g. "scripts/scan.jl".
        argv_list: One entry per point; each a comma-separated argv string → Julia ARGS[1..], e.g.
            ["params/p00.json,data/p00.json", "params/p01.json,data/p01.json"].
        timeout_s: Per-point max wall-clock seconds. 0 (default) uses the configured run timeout,
            {_RUN_TIMEOUT_S}s on this run. Pass 0 rather than a smaller guess.
        max_parallel: Max points to run at once. 0 (default) uses the configured cap, which on
            THIS run is {_BATCH_MAX_PARALLEL}. Pass 0 rather than a smaller guess: a smaller value
            OVERRIDES the cap rather than being limited by it, so it just runs the survey narrower.
    """
    return run_julia_batch_impl(code, argv_list, timeout_s=timeout_s, max_parallel=max_parallel)


def shutdown_julia() -> None:
    """Close the persistent REPL. Called by main.py on exit."""
    global _scratch
    if _scratch is not None:
        try:
            _scratch.close()
        except Exception:
            pass
        _scratch = None


# `@tool(parse_docstring=True)` puts the Args text into the argument schema, not into
# `.description`, so the budget has to be substituted there. Doing it at import means the
# model is told the real number instead of discovering it by exceeding it.
_RUNTIME_VALUES = {"{_RUN_TIMEOUT_S}": str(_RUN_TIMEOUT_S),
                   "{_BATCH_MAX_PARALLEL}": str(_BATCH_MAX_PARALLEL)}


def _fill(text: str) -> str:
    for k, v in _RUNTIME_VALUES.items():
        text = text.replace(k, v)
    return text


def _inject_timeout(tool) -> None:
    for target in (tool, getattr(tool, "args_schema", None)):
        d = getattr(target, "description", None)
        if isinstance(d, str) and any(k in d for k in _RUNTIME_VALUES):
            target.description = _fill(d)
    sch = getattr(tool, "args_schema", None)
    fields = getattr(sch, "model_fields", None) or getattr(sch, "__fields__", {}) or {}
    for f in fields.values():
        d = getattr(f, "description", None)
        if isinstance(d, str) and any(k in d for k in _RUNTIME_VALUES):
            f.description = _fill(d)
    if hasattr(sch, "model_rebuild"):
        try: sch.model_rebuild(force=True)
        except Exception: pass


for _f in (run_julia, run_julia_batch):
    _inject_timeout(_f)
