"""
src/llm/_orphan.py
Helpers for safe, job-scoped cleanup of local LLM servers.

The server manager (VllmServer) records the PID of the server it spawned in a
pid-file. On the next startup it reaps only that process group, never other
same-user servers (another terminal, a concurrent run, a shared daemon). This
is the `startup_cleanup="own"` path: it deliberately does not iterate over all
processes; it consults only the manager's own pid-file.

The reap targets the process group (servers are launched with
`start_new_session=True`, so the recorded PID is the group leader) so worker
children are reaped as well.
"""

from __future__ import annotations

import os
import signal
from pathlib import Path


def write_pidfile(path, pid: int) -> None:
    """Record the PID of the server we just spawned. Best-effort: a pid-file
    problem must never break startup."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(int(pid)))
    except Exception:
        pass


def clear_pidfile(path) -> None:
    """Remove our pid-file (best-effort)."""
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass
    except Exception:
        pass


def reap_own_orphan(path, token: str, logger=None) -> None:
    """Kill ONLY the server group recorded in our own pid-file `path`.

    A process is reaped only if it is (a) alive, (b) owned by the current user,
    and (c) its name or cmdline contains `token` (e.g. "vllm"), which guards
    against PID reuse. Anything not recorded in our pid-file is never touched.
    The pid-file is always cleared afterward.
    """
    p = Path(path)
    if not p.exists():
        return
    try:
        pid = int(p.read_text().strip())
    except Exception:
        clear_pidfile(p)
        return

    try:
        import getpass
        import psutil

        same_user = False
        is_backend = False
        try:
            proc = psutil.Process(pid)
            same_user = (proc.username() == getpass.getuser())
            name = (proc.name() or "").lower()
            try:
                cmdline = " ".join(proc.cmdline()).lower()
            except Exception:
                cmdline = ""
            is_backend = (token in name) or (token in cmdline)
        except psutil.NoSuchProcess:
            pass  # stale pid-file, process already gone

        if same_user and is_backend:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
                if logger:
                    logger.info(
                        "Reaped our own orphaned %s server group (PID %d) from a prior run.",
                        token, pid,
                    )
            except ProcessLookupError:
                pass  # died between check and kill
            except Exception as e:
                if logger:
                    logger.debug("Failed to reap orphan PID %d: %s", pid, e)
        elif logger:
            logger.debug(
                "pid-file %s (PID %d) is not a live %s server owned by us; treating as stale.",
                str(p), pid, token,
            )
    except Exception as e:
        if logger:
            logger.debug("reap_own_orphan error: %s", e)
    finally:
        clear_pidfile(p)
