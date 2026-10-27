"""
qme/tools/python_exec.py

The `run_python` tool, for the agent's analysis and plotting scripts.

`run_julia` has a timeout, output truncation and convergence reporting, but without this tool
the agent's Python (matplotlib/numpy plotting, extrapolation fits) would go through a generic
shell with no guards at all. An agent-written plotting script can accidentally allocate an
enormous array (a meshgrid or broadcast blow-up), hold hundreds of GiB resident and outlive
the run that spawned it, so the same guards apply here.

Three guards, mirroring `run_julia`:

  1. Memory cap (`RLIMIT_AS`, default 32 GB), the important one. An over-allocation raises
     `MemoryError` inside the script, a normal traceback the agent can read and fix itself,
     instead of taking the host down. Applied per-child via `preexec_fn`, never to the whole
     run tree: vLLM is a sibling process and CUDA reserves enormous virtual address space,
     so a tree-wide RLIMIT_AS would kill the model server.
  2. Timeout (default 300 s). Plotting and fitting take seconds, so a minutes-long script is
     a runaway. On expiry the whole process group is killed, not just the child: killing only
     the child leaves grandchildren running detached.
  3. Output truncation, so a chatty script cannot flood the context.

Result format matches `run_julia`'s so the agent reads
the same `status=OK|ERROR|TIMEOUT` header.
"""

from __future__ import annotations

import os
import resource
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from langchain_core.tools import tool

# Run dir comes from the same env var main.py sets for the Julia tools.
_RUN_DIR = os.environ.get("QME_RUN_DIR")
RUN_DIR = Path(_RUN_DIR).resolve() if _RUN_DIR else None

DEFAULT_TIMEOUT_S = int(os.environ.get("QME_PYTHON_TIMEOUT_S", "300"))
# 32 GB: far above any legitimate plot or fit over this project's data (a run's whole
# data/ directory is tens of MB), far below what an unbounded blow-up can reach.
MEM_LIMIT_BYTES = int(os.environ.get("QME_PYTHON_MEM_GB", "32")) * 1024**3
MAX_OUTPUT_CHARS = 20_000


def _limit_memory() -> None:
    """preexec_fn: cap the child's address space. Runs in the child after fork."""
    resource.setrlimit(resource.RLIMIT_AS, (MEM_LIMIT_BYTES, MEM_LIMIT_BYTES))
    # Also cap core dumps: a 32 GB core file would be its own disk problem.
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _truncate(s: str, n: int = MAX_OUTPUT_CHARS) -> str:
    return s if len(s) <= n else s[:n] + f"\n…[truncated, {len(s) - n} more chars]"


def run_python_impl(code: str, timeout_s: int = 0) -> str:
    """Execute `code` (inline source, or a .py path inside the run dir) under the guards."""
    timeout_s = timeout_s or DEFAULT_TIMEOUT_S
    cwd = str(RUN_DIR) if RUN_DIR else None

    # A path is only accepted inside the run dir: an LLM should not be able to execute
    # arbitrary .py files elsewhere on disk. Inline code is written to run_dir/scripts/.
    candidate = Path(code.strip())
    script_path: Path | None = None
    tmp_path: Path | None = None
    if code.strip().endswith(".py") and "\n" not in code.strip():
        p = candidate if candidate.is_absolute() else ((RUN_DIR / candidate) if RUN_DIR else candidate)
        p = p.resolve()
        if RUN_DIR is not None:
            try:
                p.relative_to(RUN_DIR)
            except ValueError:
                return (f"status=ERROR wall=0.0s rc=None\n"
                        f"(run_python blocked: {p} is outside the run folder {RUN_DIR}. "
                        f"Write the script inside the run dir first.)")
        script_path = p

    if script_path is None:
        tmp_dir = (RUN_DIR / "scripts") if RUN_DIR is not None else None
        if tmp_dir is not None:
            tmp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False,
                                         encoding="utf-8",
                                         dir=(str(tmp_dir) if tmp_dir else None)) as tmp:
            tmp.write(code)
            tmp_path = Path(tmp.name)
        script_path = tmp_path

    cmd = ["python3", str(script_path)]
    t0 = time.monotonic()
    timed_out = False
    rc, stdout, stderr = -1, "", ""
    proc = None
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            preexec_fn=_limit_memory,      # guard 1
            start_new_session=True,        # own process group -> killable as a unit
        )
        stdout, stderr = proc.communicate(timeout=timeout_s)   # guard 2
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        # Kill the group, not just the child: killing only the child leaves
        # grandchildren running detached, which is exactly how a runaway script
        # outlives its run. start_new_session=True made the child the group leader,
        # so the group id is its pid.
        pgid = proc.pid
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        # The leader exiting does not mean the group is empty: a descendant that
        # ignores SIGTERM survives it. Always follow with SIGKILL to the group;
        # ProcessLookupError here means every member is already gone. (A process
        # that put itself in a new session is beyond the group's reach, as with
        # any group-based kill.) Thanks to Massimiliano Brighindi for reporting
        # the surviving-descendant case.
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)   # reap the leader so no zombie outlives the call
        except subprocess.TimeoutExpired:
            pass
        stdout, stderr = "", f"(timeout after {timeout_s}s, process group killed)"
    except FileNotFoundError as exc:
        return f"status=ERROR wall=0.0s rc=None\n(run_python: interpreter not found: {exc})"
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass

    wall = time.monotonic() - t0
    status = "OK" if (rc == 0 and not timed_out) else ("TIMEOUT" if timed_out else "ERROR")
    head = f"status={status} wall={wall:.1f}s rc={rc}"
    # MemoryError is the guard doing its job. Say so, so the agent fixes the array size
    # instead of retrying the same allocation.
    if "MemoryError" in stderr or "Cannot allocate memory" in stderr:
        head += (f"\n(HINT: the {MEM_LIMIT_BYTES // 1024**3} GB memory cap was hit. This is almost "
                 f"always an accidentally huge array: check meshgrid/linspace sizes and any "
                 f"outer product or broadcast, e.g. X[:,None] - Y[None,:].)")
    body = ""
    if stdout.strip():
        body += f"\n--- stdout ---\n{_truncate(stdout)}"
    if stderr.strip():
        body += f"\n--- stderr ---\n{_truncate(stderr)}"
    return head + body


@tool(parse_docstring=True)
def run_python(code: str, timeout_s: int = 0) -> str:
    """Run a Python script for ANALYSIS or PLOTTING (matplotlib, numpy fits, extrapolation).

    Use this for every Python script (never the raw shell), because it enforces a memory
    cap and a timeout. Julia/DMRG work still goes through `run_julia`.

    The script runs with the run directory as its working directory, so relative paths like
    `data/…` and `plots/…` work as usual. Save figures as PNG rather than SVG: a vector file
    of a dense plot can reach tens of MB and is unreadable anyway.

    Args:
        code: Inline Python source, OR the path to a .py file inside the run directory.
        timeout_s: Seconds before the script is killed. 0 uses the default (300 s).

    Returns:
        `status=OK|ERROR|TIMEOUT wall=…s rc=…` followed by stdout/stderr (truncated). A
        MemoryError means the memory cap caught an over-allocation, so fix the array size.
    """
    return run_python_impl(code, timeout_s=timeout_s)
