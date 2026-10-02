"""
src/tools/helpers.py

Small custom tools for the deep agent:

  - validate:   sub-second syntax check of Python/Julia before paying a launch.
  - lookup_doc: grep the local ITensor library mirror for a symbol's definition.
  - update_run_summary: one reliable call to append to <run>/RUN_SUMMARY.md.
  - finish:     explicit done signal, writes the `.finished` sentinel so the run
                driver stops cleanly instead of re-nudging a finished agent.

Run-dir / lib path come from the QME_* env vars set by main.py (see sandbox.py).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time

from langchain_core.tools import tool

from .sandbox import RUN_DIR, resolve_read, assert_writable


# --- validate ---

def _run_validation(cmd: list[str], label: str, timeout_s: int,
                    stdin_text: str = "") -> str:
    try:
        proc = subprocess.run(
            cmd, input=stdin_text if stdin_text else None,
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return f"(validate [{label}]: timed out after {timeout_s}s)"
    except FileNotFoundError as exc:
        return f"(validate [{label}]: executable not found: {exc})"
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode == 0 and out.endswith("OK"):
        return "OK"
    body = "\n".join(s for s in (out, err) if s) or f"(exit {proc.returncode})"
    return f"(validate [{label}] FAILED)\n{body}"


@tool(parse_docstring=True)
def validate(code_or_path: str, language: str = "auto", timeout_s: int = 30) -> str:
    """Syntax-check Python or Julia (pure parse, no execution) before running it.

    `code_or_path` is EITHER a path on disk (auto-detected) OR raw source code.
    Cheap insurance: catch syntax errors in milliseconds instead of paying a full
    Julia launch.

    Args:
        code_or_path: A file path (run-dir-relative or absolute) OR raw source.
        language: 'python' | 'julia' | 'auto' (auto only works for a recognised file extension).
        timeout_s: Max seconds for the parse check.
    """
    is_path = False
    p = None
    if len(code_or_path) < 4096 and "\n" not in code_or_path:
        try:
            p = resolve_read(code_or_path)
            is_path = p.exists() and p.is_file()
        except Exception:
            pass

    if is_path:
        if language == "auto":
            language = {".py": "python", ".jl": "julia"}.get(p.suffix.lower(), "")
        if language not in ("python", "julia"):
            return (f"(validate: cannot infer language from {p.suffix!r}. "
                    f"Pass language='python' or language='julia'.)")
        try:
            code_text = p.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return f"(validate: cannot read {p}: {exc})"
        source_label = str(p)
    else:
        if language == "auto":
            return ("(validate: when passing raw code, set language='python' or 'julia'.)")
        if language not in ("python", "julia"):
            return f"(validate: unsupported language {language!r}.)"
        code_text = code_or_path
        source_label = "<inline>"

    if language == "python":
        py = ("import sys, ast\n"
              "try:\n"
              f"  ast.parse(sys.stdin.read(), filename={source_label!r})\n"
              "  print('OK')\n"
              "except SyntaxError as e:\n"
              "  print(f'{e.__class__.__name__}: {e}')\n"
              "  sys.exit(1)\n")
        return _run_validation([sys.executable, "-c", py], "python", timeout_s, stdin_text=code_text)

    julia_exe = os.environ.get("QME_JULIA_EXE", "julia")
    jl = ('src = read(stdin, String); '
          'try; Meta.parse(src, 1); println("OK"); '
          'catch e; println(e); exit(1); end')
    cmd = [julia_exe, "--startup-file=no", "--quiet", "-e", jl]
    return _run_validation(cmd, "julia", timeout_s, stdin_text=code_text)


# --- lookup_doc ---

@tool(parse_docstring=True)
def lookup_doc(symbol: str, lib_path: str = "", max_matches: int = 3) -> str:
    """Find an ITensor/ITensorMPS symbol's definition in the local library mirror.

    Greps the checked-out ITensor sources for `function <symbol>(`, `<symbol>(...) =`,
    then any `<symbol>` reference, returning the first few matches with context.
    More targeted than a raw grep when you need a function's real signature/kwargs.

    Args:
        symbol: The Julia symbol to look up (e.g. "dmrg", "siteinds", "expect").
        lib_path: Optional library root, defaults to $QME_ITENSOR_LIB.
        max_matches: Maximum number of match snippets to return.
    """
    root_str = lib_path or os.environ.get("QME_ITENSOR_LIB", "")
    if not root_str:
        return (f"(lookup_doc: no library path configured. Set QME_ITENSOR_LIB or pass "
                f"lib_path. Symbol requested: {symbol!r})")
    root = resolve_read(root_str)
    if not root.exists():
        return f"(lookup_doc: library path {root} does not exist)"

    patterns = [
        re.compile(rf"^\s*function\s+{re.escape(symbol)}\b"),
        re.compile(rf"^\s*{re.escape(symbol)}\s*\(.*\)\s*=", re.MULTILINE),
        re.compile(rf"\b{re.escape(symbol)}\b"),
    ]
    matches: list[str] = []
    for src in root.rglob("*.jl"):
        try:
            lines = src.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for pat in patterns:
            for i, line in enumerate(lines):
                if pat.search(line):
                    start = max(0, i - 1)
                    end = min(len(lines), i + 8)
                    snippet = "\n".join(f"{start+j+1:04d} | {lines[start+j]}" for j in range(end - start))
                    matches.append(f"-- {src} (line {i+1}) --\n{snippet}")
                    if len(matches) >= max_matches:
                        return "\n\n".join(matches)
                    break
            if matches and matches[-1].startswith(f"-- {src}"):
                break
    if not matches:
        return f"(lookup_doc: no definition found for {symbol!r} under {root})"
    return "\n\n".join(matches)


# --- update_run_summary ---

RUN_SUMMARY_FILENAME = "RUN_SUMMARY.md"


@tool(parse_docstring=True)
def update_run_summary(experiment_id: str, description: str, findings: str,
                       key_scalars: str = "", next_suggestion: str = "",
                       artifacts: str = "") -> str:
    """Append one compressed entry to <run>/RUN_SUMMARY.md (durable results memory).

    One reliable call beats read→reformat→write. This is your append-only memory of
    what each experiment found. It survives context summarization, so record every
    result here as it lands.

    Args:
        experiment_id: Short id, e.g. "exp_03_j2_050".
        description: One line on what this experiment was.
        findings: 2-3 sentences on what the data showed (physics).
        key_scalars: Optional compact scalars, e.g. "energy_per_site=-0.4374, q*=pi".
        next_suggestion: Optional one line on what to do next.
        artifacts: The files behind this entry, when there are any: the script that produced
            the numbers and the outputs it wrote, e.g.
            "scripts/scan_j2.jl -> data/j2_*.json, plots/j2_cuts.png".
            A finding recorded without its files cannot be re-derived by anyone reading
            this later, including you after a summarisation.

            Record the path to the result AS IT STANDS, not the history of getting there.
            A script you crashed and fixed, a typo, a run you relaunched: leave all of it
            out. The exception is a failure that changed the result, because then it is
            part of the result: three points that timed out and were excluded belong here,
            since otherwise the coverage looks complete when it is not.

            Omit entirely when the entry used no files (a decision, a plan revision, a
            reasoning step).
    """
    if RUN_DIR is None:
        return "(update_run_summary: QME_RUN_DIR not set)"
    out_path = assert_writable(RUN_DIR / RUN_SUMMARY_FILENAME)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    if not out_path.exists():
        out_path.write_text(
            "# Run Summary\n\nAppend-only compressed record of what each experiment found.\n",
            encoding="utf-8",
        )
    parts = ["", f"## {experiment_id}  ({timestamp})", f"Description: {description.strip()}"]
    if key_scalars.strip():
        parts.append(f"Key scalars: {key_scalars.strip()}")
    if artifacts.strip():
        parts.append(f"Artifacts: {artifacts.strip()[:400]}")
    parts.append(f"Findings: {findings.strip()[:1200]}")
    if next_suggestion.strip():
        parts.append(f"Next: {next_suggestion.strip()[:300]}")
    parts.extend(["---", ""])
    with open(out_path, "a", encoding="utf-8") as f:
        f.write("\n".join(parts))
    return f"(update_run_summary: appended {experiment_id} → {out_path})"


# --- finish ---

FINISHED_SENTINEL = ".finished"


@tool(parse_docstring=True)
def finish(reason: str) -> str:
    """Finalize and submit the COMPLETED study. This ENDS the run.

    Call this ONCE, and only when the full phase-diagram study is genuinely
    complete: the survey / boundaries / order-ID / finite-size scaling are done,
    every key result is shown as an embedded figure, the results are validated, and
    `note/research_note.md` has its `## Phase diagram` and `## Conclusion`. This is
    a deliberate, terminal action: it writes a `.finished` sentinel that tells the
    run driver to stop cleanly (no more continuation nudges). Do NOT call it to
    pause or mid-study, and once the study IS done call it instead of re-polishing a
    finished note.

    The physics-critic's latest verdict is the authority on completeness: if your
    most recent physics-critic review returned a BLOCKER, the study is by definition
    NOT complete, so do NOT finish. Either do the feasible fix and re-run, or downgrade
    the claim to exactly what the data supports, then get a fresh critic review that
    CLEARS (VERDICT: PASS) before finishing.

    Args:
        reason: One or two sentences stating WHY the study is complete: what phase
            diagram you characterized and that the note + figures are in place.
    """
    if RUN_DIR is None:
        return "(finish: QME_RUN_DIR not set)"
    # HITL guard (only when human-in-the-loop is on): finishing is allowed only after the
    # human approved the final review (request_review wrote `.review_approved`). Keeps `finish`
    # otherwise pure: this is the one-line gate, not review logic.
    if os.environ.get("QME_HITL", "0") == "1" and not (RUN_DIR / ".review_approved").exists():
        return ("(finish refused: human-in-the-loop is ON. Call request_review and get an "
                "approved (empty-comments) final review BEFORE finishing.)")
    # Staleness guard. The reporting instructions already require the note and
    # `phase_diagram.json` to agree, but it is easy to write the JSON and then edit the note
    # again. Ordering is mechanical, so check it here rather than asking again in prose. This
    # catches a stale file, not a contradictory one: content disagreement is the critic's job.
    pd = RUN_DIR / "phase_diagram.json"
    note = RUN_DIR / "note" / "research_note.md"
    if not pd.exists():
        return ("(finish refused: phase_diagram.json is missing. Write the machine-readable phase "
                "diagram (same regions, labels and hedging as the note), then finish.)")
    if note.exists() and pd.stat().st_mtime < note.stat().st_mtime:
        return ("(finish refused: phase_diagram.json is OLDER than note/research_note.md, so it "
                "predates your final edits and no longer matches them. Rewrite it from the note as "
                "it now stands, then finish.)")

    out_path = assert_writable(RUN_DIR / FINISHED_SENTINEL)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    out_path.write_text(f"finished_at: {timestamp}\nreason: {reason.strip()}\n", encoding="utf-8")
    return (f"(finish: study marked COMPLETE at {timestamp}. The run will now end. "
            f"No further work is needed, do not continue.)")
