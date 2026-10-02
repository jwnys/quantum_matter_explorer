"""
src/tools/julia_scratch.py

A persistent Julia subprocess the agent can poke at, the human "open the
REPL and try a small thing first" workflow.

State persists across `evaluate()` calls: defining `sites = siteinds(...)`
in one call leaves it accessible in the next. Each evaluate() returns the
captured stdout/stderr produced by that snippet only, demarcated by a
unique sentinel.

Lifetime: instantiated lazily, closed via try/finally. The Julia process
pays a ~3-5s startup cost per construction, which is acceptable given the
alternative is paying that cost per failed DMRG crash cycle.
"""

from __future__ import annotations

import os
import queue
import shlex
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ScratchResult:
    """Output of a single evaluate() call."""
    ok: bool
    stdout: str
    stderr: str
    wall_time_s: float
    timed_out: bool = False


class JuliaScratch:
    """Persistent Julia subprocess with a line-oriented evaluate() protocol.

    Each `evaluate(code)` call:
      1. Pipes the code into the subprocess stdin.
      2. Then pipes a sentinel-printing line that emits a unique token on
         both stdout and stderr so we can detect completion on each stream
         independently.
      3. Reader threads accumulate stdout/stderr until both have seen the
         sentinel (or we time out).

    The sentinel approach is robust against the model's snippet doing its
    own `println` or having unbalanced output between the two streams.
    """

    # Banner printed when the process is ready to evaluate user code.
    _READY_MARKER = "__JULIA_SCRATCH_READY__"

    def __init__(self, julia_cfg: dict[str, Any], launch_timeout_s: float = 30.0) -> None:
        self.julia_cfg = julia_cfg
        self._proc: subprocess.Popen | None = None
        self._stdout_q: queue.Queue[str] = queue.Queue()
        self._stderr_q: queue.Queue[str] = queue.Queue()
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._start(launch_timeout_s)

    # --- lifecycle ---

    def _start(self, launch_timeout_s: float) -> None:
        exe = self.julia_cfg.get("executable", "julia")
        proj = self.julia_cfg.get("project_dir", "./output/julia_project")
        # Disable banner and use unbuffered stdout so reader threads see
        # output immediately rather than in 8KB chunks.
        cmd = [exe, "--startup-file=no", "--quiet",
               "-i",  # interactive REPL, accepts code on stdin
               "-e", f"using Pkg; print(\"{self._READY_MARKER}\\n\"); flush(stdout)"]
        if proj:
            cmd.insert(1, f"--project={proj}")

        env = dict(os.environ)
        env["JULIA_NUM_THREADS"] = env.get("JULIA_NUM_THREADS", "auto")

        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,           # line-buffered
            env=env,
            preexec_fn=os.setsid if hasattr(os, "setsid") else None,
        )

        self._stdout_thread = threading.Thread(
            target=_drain, args=(self._proc.stdout, self._stdout_q), daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=_drain, args=(self._proc.stderr, self._stderr_q), daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

        # Wait for the ready banner before accepting evaluate() calls.
        deadline = time.time() + launch_timeout_s
        seen = False
        while time.time() < deadline:
            try:
                line = self._stdout_q.get(timeout=0.5)
            except queue.Empty:
                if self._proc.poll() is not None:
                    raise RuntimeError(
                        f"Julia scratch process exited during startup. "
                        f"stderr: {self._drain_q(self._stderr_q)}"
                    )
                continue
            if self._READY_MARKER in line:
                seen = True
                break
        if not seen:
            self.close()
            raise RuntimeError(
                f"Julia scratch did not become ready within {launch_timeout_s}s"
            )

    def restart(self) -> None:
        """Kill and respawn. Used when a snippet wedges the session."""
        launch_timeout = self.julia_cfg.get("launch_timeout_seconds", 30)
        self.close()
        self._stdout_q = queue.Queue()
        self._stderr_q = queue.Queue()
        self._start(launch_timeout)

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.poll() is None:
                if hasattr(os, "killpg"):
                    try:
                        os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                else:
                    self._proc.terminate()
                try:
                    self._proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
        finally:
            self._proc = None

    def __enter__(self) -> "JuliaScratch":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- evaluation ---

    def evaluate(self, code: str, timeout_s: float = 30.0,
                 max_output_chars: int = 4000) -> ScratchResult:
        """Pipe `code` to the running session, return its output.

        The session emits a unique sentinel on both stdout and stderr after
        executing the snippet, and we accumulate output until both streams
        have seen their sentinel (or we time out).
        """
        if self._proc is None or self._proc.poll() is not None:
            return ScratchResult(ok=False, stdout="", stderr="(scratch session is not running)",
                                 wall_time_s=0.0)

        sentinel = f"__SCRATCH_END_{uuid.uuid4().hex[:12]}__"
        # Drain any leftover from a previous call.
        self._drain_q(self._stdout_q)
        self._drain_q(self._stderr_q)

        # Don't wrap the user snippet in `try ... end`: doing so makes any
        # `x = 42` inside the snippet a local variable of the try-block, so
        # persistent state would silently break (assignment lost between
        # evaluate() calls). At Julia's REPL top-level, an unhandled error
        # prints to stderr and the REPL continues, which is exactly what we want.
        # The sentinel printed after the snippet runs in either case.
        # `;` between user code and sentinel makes them separate statements
        # even when the user code lacks a trailing newline.
        wrapped = (
            f"{code}\n"
            f"println(stdout, \"{sentinel}\"); flush(stdout); "
            f"println(stderr, \"{sentinel}\"); flush(stderr)\n"
        )

        t0 = time.time()
        try:
            self._proc.stdin.write(wrapped)
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            return ScratchResult(ok=False, stdout="",
                                 stderr=f"(broken stdin: {e})",
                                 wall_time_s=time.time() - t0)

        # Collect output until both sentinels seen.
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        seen_out = seen_err = False
        timed_out = False
        out_chars = err_chars = 0

        while not (seen_out and seen_err):
            remaining = timeout_s - (time.time() - t0)
            if remaining <= 0:
                timed_out = True
                break
            advanced = False
            if not seen_out:
                try:
                    line = self._stdout_q.get(timeout=min(0.1, remaining))
                    advanced = True
                    if sentinel in line:
                        # everything before the sentinel on this line is real output
                        head = line.split(sentinel, 1)[0]
                        if head:
                            stdout_chunks.append(head)
                        seen_out = True
                    else:
                        stdout_chunks.append(line)
                        out_chars += len(line)
                except queue.Empty:
                    pass
            if not seen_err:
                try:
                    line = self._stderr_q.get(timeout=min(0.1, remaining))
                    advanced = True
                    if sentinel in line:
                        head = line.split(sentinel, 1)[0]
                        if head:
                            stderr_chunks.append(head)
                        seen_err = True
                    else:
                        stderr_chunks.append(line)
                        err_chars += len(line)
                except queue.Empty:
                    pass
            if not advanced and self._proc.poll() is not None:
                # Process died.
                stderr_chunks.append(f"\n(scratch process exited with code {self._proc.returncode})")
                break

        wall = time.time() - t0
        stdout = "".join(stdout_chunks)
        stderr = "".join(stderr_chunks)

        # Truncate to budget for the prompt.
        if len(stdout) > max_output_chars:
            stdout = stdout[:max_output_chars] + f"\n... [truncated, {len(stdout) - max_output_chars} more chars]"
        if len(stderr) > max_output_chars:
            stderr = stderr[:max_output_chars] + f"\n... [truncated, {len(stderr) - max_output_chars} more chars]"

        return ScratchResult(
            ok=(not timed_out) and ("ERROR" not in stderr) and ("rror" not in stderr.lower() or stderr.strip() == ""),
            stdout=stdout,
            stderr=stderr,
            wall_time_s=wall,
            timed_out=timed_out,
        )

    # --- helpers ---

    @staticmethod
    def _drain_q(q: queue.Queue) -> str:
        out = []
        while True:
            try:
                out.append(q.get_nowait())
            except queue.Empty:
                break
        return "".join(out)


def _drain(stream, q: queue.Queue) -> None:
    """Reader thread: pump every line from a pipe into a queue."""
    try:
        for line in iter(stream.readline, ""):
            if not line:
                break
            q.put(line)
    except Exception:
        pass
    finally:
        try:
            stream.close()
        except Exception:
            pass
