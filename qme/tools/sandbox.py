"""
qme/tools/sandbox.py

Write-sandbox for the agent's tools. Reads are unrestricted (full filesystem).
Writes must land inside `$QME_RUN_DIR`, the timestamped output folder for the
current run.

Two env vars, set by main.py before the tools are imported:
  - QME_RUN_DIR:   absolute path to this run's output folder (write root)
  - QME_REPO_ROOT: absolute path to the repo root (for context only)

If `QME_ISOLATE_WRITES` is "0", `assert_writable` becomes a no-op.
"""

from __future__ import annotations

import os
from pathlib import Path


def _env_path(name: str) -> Path | None:
    v = os.environ.get(name)
    if not v:
        return None
    try:
        return Path(v).expanduser().resolve()
    except Exception:
        return None


RUN_DIR: Path | None = _env_path("QME_RUN_DIR")
REPO_ROOT: Path | None = _env_path("QME_REPO_ROOT")
ISOLATE_WRITES: bool = os.environ.get("QME_ISOLATE_WRITES", "1") != "0"


class SandboxError(PermissionError):
    """Raised by `assert_writable` on attempted out-of-sandbox writes."""


def assert_writable(path: str | Path) -> Path:
    """Resolve `path` and verify it lives inside `$QME_RUN_DIR`.

    A bare relative path (e.g. "main.jl", "scripts/foo.jl") is anchored
    inside `$QME_RUN_DIR` rather than the process cwd (the repo root),
    because that is what the LLM almost always means when it asks to
    "write main.jl". Resolving against the repo root and rejecting the
    write as outside the sandbox would be a usability cliff. Absolute
    paths still resolve as given.

    Symlinks are resolved so `../` escapes can't reach outside the run
    folder. Returns the resolved path on success, and raises SandboxError
    on failure with a clear message that surfaces to the LLM as the
    tool result.
    """
    p_in = Path(path).expanduser()
    # Relative path: anchor to RUN_DIR. If RUN_DIR is unset we let
    # Path.resolve() resolve against cwd and the sandbox check below
    # will reject.
    if not p_in.is_absolute() and RUN_DIR is not None:
        p = (RUN_DIR / p_in).resolve()
    else:
        p = p_in.resolve()
    if not ISOLATE_WRITES:
        return p
    if RUN_DIR is None:
        raise SandboxError(
            "Write blocked: QME_RUN_DIR is not set. The tools were loaded "
            "without a run folder. Writes are disabled."
        )
    if p != RUN_DIR and RUN_DIR not in p.parents:
        raise SandboxError(
            f"Write blocked: {p} is outside the run folder {RUN_DIR}. "
            f"Writes are only permitted inside the run output dir."
        )
    return p


def resolve_read(path: str | Path) -> Path:
    """Resolve a path for reading. No restriction: full filesystem access.

    Relative paths are anchored to `$QME_RUN_DIR` (not the process cwd)
    so the LLM's natural `read_file("data/foo.json")` style finds the
    run's data files instead of looking for them at the repo root.
    Absolute paths resolve as given. This makes the read-side tools
    behave the same way the write-side ones already do.
    """
    p_in = Path(path).expanduser()
    if not p_in.is_absolute() and RUN_DIR is not None:
        return (RUN_DIR / p_in).resolve()
    return p_in.resolve()
