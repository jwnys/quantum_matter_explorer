"""
qme/agent.py
Assemble the single deep agent: one research agent plus its tools, subagents,
and middleware.

`build_agent(cfg, run_dir, model)` returns a compiled deep agent with:
  - a real-disk backend rooted at the run folder (virtual_mode gives the agent
    run-dir-relative, sandboxed file tools; `execute` runs in the run dir);
  - the custom tools (run_julia, run_julia_batch, run_python, validate,
    lookup_doc, update_run_summary, finish) on top of deepagents' built-ins
    (write_todos, filesystem, execute, task);
  - two subagents (data-analyst, physics-critic) plus the automatic
    general-purpose one;
  - skills (a progressive-disclosure domain reference library);
  - percent-based auto-summarization (wired via the model profile), a manual
    `compact_conversation` tool, and an incremental-output nudge.
"""

from __future__ import annotations

import logging
import json
import re
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from deepagents.middleware.summarization import create_summarization_tool_middleware
from langchain.agents.middleware.types import AgentMiddleware
from deepagents.middleware._utils import append_to_system_message
from langgraph.checkpoint.memory import InMemorySaver

from qme.llm.provider import resolve_agent_provider
from qme.tools.julia import run_julia, run_julia_batch
from qme.tools.python_exec import run_python
from qme.tools.helpers import validate, lookup_doc, update_run_summary, finish
from qme.context_guard import ContextOverflowClassifier
from qme.image_guard import ImageReadGuard
from qme.tool_error_guard import ToolErrorGuard
from qme.rate_limit import RateLimitRetryMiddleware, TokenRateLimitMiddleware
from qme.tools.hitl import request_plan_review, request_review, PLAN_REVIEWED
from qme.prompts import (
    MAIN_SYSTEM_PROMPT,
    HITL_PROMPT_SNIPPET,
    DATA_ANALYST_PROMPT,
    DATA_ANALYST_DESCRIPTION,
    PHYSICS_CRITIC_PROMPT,
    PHYSICS_CRITIC_DESCRIPTION,
)

logger = logging.getLogger("qme.agent")

DEFAULT_CONTEXT_LENGTH = 131072


def context_length(cfg: dict[str, Any]) -> int:
    """Resolve the served model's context window from the active provider sub-config."""
    _, sub = resolve_agent_provider(cfg.get("llm", {}) or {}, "")
    return int(sub.get("context_length", DEFAULT_CONTEXT_LENGTH))


def set_summarization_profile(model: BaseChatModel, ctx: int, headroom: float = 1.0,
                              absolute: int = 0) -> bool:
    """Wire auto-summarization: set the model's `max_input_tokens` profile so deepagents'
    summarization auto-selects fraction-based thresholds (trigger at 0.85 of the window,
    keep 0.10) instead of its fixed default.

    Two ways to say the same thing, and `absolute` wins when both are given:

      `absolute`  is `agent.max_input_tokens`, a token count. Preferred when you want a
                  specific budget: "compact at ~190k" reads directly instead of having to
                  be recovered from a fraction of a window. It is also the only way to give
                  two models with different context windows the same effective budget,
                  which is what a backbone comparison needs, since a shared fraction gives
                  them different absolute budgets.
      `headroom`  is `agent.summary_headroom`, a fraction of the served context window.
                  Its purpose is to shave the window so summarization fires before a token
                  undercount can overflow it: `count_tokens_approximately` reads low
                  against a real tokenizer, so at headroom=1.0 the 0.85 trigger is reached
                  only after the real prompt already passed 100% of the window (an
                  overflow crash). A headroom of 0.85 puts the effective trigger near
                  0.72 of the real context, leaving margin for one large turn.

    Note the resulting trigger is 0.85 of whatever this sets, not the value itself.
    Returns True if the profile was set."""
    effective = max(1, int(absolute)) if absolute else max(1, int(ctx * headroom))
    try:
        model.profile = {**(getattr(model, "profile", None) or {}), "max_input_tokens": effective}
        return True
    except Exception as exc:  # pragma: no cover
        logger.warning("Could not set model.profile (summarization will use defaults): %s", exc)
        return False


class IncrementalOutputNudge(AgentMiddleware):
    """Soft-enforcement reminders (never blocks). Triggers:

    (a) loop: many `run_julia` calls with no new `data/*.json` written, the clean
        "looping, not progressing" signal. Nudges the agent to smoke-test smaller,
        raise the timeout, cut bond dimension or size, or step back.
    (b) edit thrash: one file edited many times without being run. Nudges the
        agent to execute and see the actual error instead of editing blind.
    (c) stale note: several completed (fresh) DMRG runs since the note was last
        updated. Nudges the incremental-output habit.
    (d) stale RUN_SUMMARY: several completed runs since the last `update_run_summary`
        call. Tracked independently of the note, because the model tends to keep the
        note current while letting RUN_SUMMARY rot after the early survey.
    """

    def __init__(self, run_dir, note_substr: str = "research_note",
                 every_k: int = 4, loop_k: int = 6, thrash_k: int = 8,
                 summary_k: int = 6) -> None:
        super().__init__()
        self.run_dir = Path(run_dir)
        self.note_substr = note_substr
        self.every_k = max(1, int(every_k))
        self.loop_k = max(2, int(loop_k))
        self.thrash_k = max(3, int(thrash_k))
        self.summary_k = max(1, int(summary_k))
        self._max_data = -1            # most data/*.json files seen so far
        self._runs_at_max_data = 0     # run_julia count when that max was reached

    def _runs_since_note(self, messages: list) -> int:
        count = 0
        for m in messages:
            if not isinstance(m, AIMessage):
                continue
            for tc in (m.tool_calls or []):
                name = tc.get("name")
                args = tc.get("args") or {}
                if (name == "run_julia" and args.get("fresh")) or name == "run_julia_batch":
                    count += 1
                elif name in ("write_file", "edit_file") and self.note_substr in str(args.get("file_path", "")):
                    count = 0
        return count

    def _runs_since_summary(self, messages: list) -> int:
        """Completed (fresh) DMRG runs since the last `update_run_summary` call.
        Independent of the note counter: RUN_SUMMARY tends to rot once the note
        exists, so it needs its own staleness signal."""
        count = 0
        for m in messages:
            if not isinstance(m, AIMessage):
                continue
            for tc in (m.tool_calls or []):
                name = tc.get("name")
                if (name == "run_julia" and (tc.get("args") or {}).get("fresh")) or name == "run_julia_batch":
                    count += 1
                elif name == "update_run_summary":
                    count = 0
        return count

    def _total_run_julia(self, messages: list) -> int:
        return sum(1 for m in messages if isinstance(m, AIMessage)
                   for tc in (m.tool_calls or []) if tc.get("name") in ("run_julia", "run_julia_batch"))

    def _data_count(self) -> int:
        try:
            return len(list((self.run_dir / "data").glob("*.json")))
        except Exception:
            return 0

    def _edit_thrash(self, messages: list) -> tuple[str | None, int]:
        """Most-edited file (count of `edit_file` calls) since the last `run_julia`.
        Any `run_julia` resets the counters: the loop this catches is editing a file
        repeatedly without running it to test."""
        counts: dict[str, int] = {}
        for m in messages:
            if not isinstance(m, AIMessage):
                continue
            for tc in (m.tool_calls or []):
                name = tc.get("name")
                if name in ("run_julia", "run_julia_batch"):
                    counts = {}            # running clears "edited-without-testing"
                elif name in ("edit_file", "write_file"):
                    fp = str((tc.get("args") or {}).get("file_path", "?"))
                    counts[fp] = counts.get(fp, 0) + 1
        if not counts:
            return None, 0
        fp = max(counts, key=counts.get)
        return fp, counts[fp]

    def wrap_model_call(self, request, handler):
        msgs = request.state.get("messages", [])
        reminders: list[str] = []

        # (a) loop detector: runs since the data/ folder last grew
        dc = self._data_count()
        rj = self._total_run_julia(msgs)
        if dc > self._max_data:
            self._max_data, self._runs_at_max_data = dc, rj
        runs_without_data = rj - self._runs_at_max_data
        if runs_without_data >= self.loop_k:
            reminders.append(
                f"[reminder] {runs_without_data} run_julia calls since the last new data/*.json "
                f"(data files so far: {dc}). You are likely LOOPING, not progressing. Step back: "
                f"smoke-test at a SMALL L/χ first; for a full DMRG pass a larger timeout_s (runs take "
                f"minutes) or reduce χ (≤256 for the survey) / L. Do NOT keep re-running the same heavy "
                f"settings; if a script keeps failing, fix the root cause or simplify it."
            )

        # (b) edit/read thrash: editing a file repeatedly without running it
        if not reminders:
            fp, ec = self._edit_thrash(msgs)
            if ec >= self.thrash_k:
                reminders.append(
                    f"[reminder] You've edited {fp} {ec}x without running it. RUN it now to see the "
                    f"ACTUAL error: `validate` first, then a fast `fresh=False` REPL probe of the changed "
                    f"function (or `fresh=True` at a tiny L for the whole script). Editing/reading a file "
                    f"blindly in a loop fixes nothing. If an observable is "
                    f"hard to implement (e.g. dimerization), SIMPLIFY it (use the `correlation_matrix` "
                    f"recipe in the itensor-dmrg skill) or DEFER it and move on. Do not thrash."
                )

        # (c) stale-note nudge (only if not already nudging)
        if not reminders:
            n = self._runs_since_note(msgs)
            if n >= self.every_k:
                reminders.append(
                    f"[reminder] {n} DMRG experiments have run since note/research_note.md was last "
                    f"updated. Per the incremental-output rule: save the relevant figure(s) into "
                    f"plots/, embed them into note/research_note.md as `../plots/name.png` (the note "
                    f"is in note/, so the embed path needs the leading ../), add the new findings, "
                    f"and append to RUN_SUMMARY.md NOW, before launching more runs."
                )

        # (d) stale-RUN_SUMMARY nudge: fires when the note is kept fresh but RUN_SUMMARY is not
        if not reminders:
            s = self._runs_since_summary(msgs)
            if s >= self.summary_k:
                reminders.append(
                    f"[reminder] {s} DMRG experiments have run since RUN_SUMMARY.md was last updated "
                    f"(via update_run_summary). It is your scalar ledger for replanning and tends to get "
                    f"forgotten once the note exists. Append the latest points NOW (tag, key scalars, "
                    f"one-line finding, next step), including the FSS/analysis results, not just the survey."
                )

        if reminders:
            new_system = append_to_system_message(request.system_message, "\n".join(reminders))
            return handler(request.override(system_message=new_system))
        return handler(request)


# Run-dir subdirs the agent refers to with virtual leading-slash paths (`/data/...`).
_VIRTUAL_DIRS = ("data", "plots", "params", "scripts", "note", "logs", "skills")
# Real on-disk skill library, used to enumerate skills when agent.skills_exclude drops some.
_REPO_SKILLS = Path(__file__).resolve().parent.parent / "skills"


def _is_gemma(cfg: dict[str, Any]) -> bool:
    """True if the served model is a Gemma (so `<|think|>` activation applies)."""
    llm = cfg.get("llm", {}) or {}
    prov = llm.get("provider", "vllm")
    name = str(((llm.get(prov, {}) or {}).get("model", "")))
    return "gemma" in name.lower()


class PathSafeExecuteMiddleware(AgentMiddleware):
    """Make `execute` robust to recurring path confusions. `execute` runs a raw shell with
    cwd=run_dir, so a path the model gets slightly wrong hits the host filesystem and fails
    ("No such file"), after which the model tends to scan `/` with `find /` or `ls -R /`.
    For the `execute` tool only, normalize three recurring path-confusion classes in the
    command (each rewrite is logged):

      1. Virtual leading-slash paths such as `/data/...` or `/plots/...` (the convention
         the file tools use) become the absolute run_dir path. `run_julia` already maps
         these itself; this is for the raw shell.
      2. A run-dir abspath tangle: the model glues a relative `<subdir>/../` prefix onto
         the run dir path with its leading slash stripped, which resolves under run_dir
         and fails. That whole tangle is rewritten back to the run dir.
      3. Host-wide scans: `find /`, `ls -R /some/host/path`, `ls /` aimed outside the run
         dir are redirected to the cwd.

    It does not touch legitimate host paths (/tmp, /usr, the Julia depot, the venv): none
    of those start with a virtual prefix at a boundary, the abspath-tangle rewrite is
    anchored to this run's exact directory, and anything already absolute is skipped.
    Applied to the main agent and the subagents, which hit the same confusions."""

    def __init__(self, run_dir) -> None:
        super().__init__()
        self.run_dir = str(Path(run_dir).resolve())
        names = "|".join(_VIRTUAL_DIRS)
        # A true leading `/` (not preceded by a word char, `/`, or `.`), then a known run-dir
        # subdir (or RUN_SUMMARY.md), then a boundary (`/`, space, quote, or end). Excluding `.`
        # is what keeps a legitimate relative `../plots/x.svg` or `./data/x` from being mangled:
        # those already resolve correctly from cwd=run_dir and must be left alone.
        self._prefix_re = re.compile(rf"(?<![\w/.])/({names}|RUN_SUMMARY\.md)(?=[/\s'\"]|$)")
        # The run dir with its leading slash stripped; the tangled token is whatever relative
        # path characters the model glued in front of it (e.g. `note/../`). Match a lazy run of
        # path chars up to the unique run-dir literal, then a boundary. A single lazy quantifier
        # (not a nested star) keeps the match linear: the nested form backtracks exponentially
        # on `../`-heavy input because `..` matches both branches, and this regex runs on every
        # `execute` command. The `(?<![\w/.])` guard means an already-absolute run-dir path only
        # ever rewrites to itself.
        run_dir_rel = re.escape(self.run_dir.lstrip("/"))
        self._tangle_re = re.compile(rf"(?<![\w/.])[\w./\-]*?{run_dir_rel}(?=[/\s'\"]|$)")

    def _rewrite(self, cmd: str) -> "tuple[str, list[str]]":
        notes: list[str] = []

        def _sub(m: "re.Match") -> str:
            notes.append(m.group(0).strip())
            return f"{self.run_dir}/{m.group(1)}"

        def _untangle(m: "re.Match") -> str:
            notes.append(f"abspath-tangle {m.group(0).strip()} -> run_dir")
            return self.run_dir

        new = self._prefix_re.sub(_sub, cmd)
        new = self._tangle_re.sub(_untangle, new)
        after, scan_notes = self._neutralize_host_scans(new)
        notes.extend(scan_notes)
        return after, notes

    def _outside(self, path: str) -> bool:
        """True if `path` is an absolute path not inside the run dir. The run dir itself
        may live under the same tree as other legitimate targets, so only paths outside
        the run dir count."""
        if not path.startswith("/"):
            return False
        p = path.rstrip("/") or "/"
        return not (p == self.run_dir or p.startswith(self.run_dir + "/"))

    def _neutralize_host_scans(self, cmd: str) -> "tuple[str, list[str]]":
        """Redirect `find`/`ls` aimed at an absolute path outside the run dir
        (`find /`, `ls -R /data0`, `ls -la /`, ...) to the cwd (the run dir), so a
        wrong-folder hunt can't dump the whole filesystem into context. Absolute
        paths inside the run dir pass untouched; relative paths are never matched."""
        notes: list[str] = []

        def _find(m: "re.Match") -> str:
            if self._outside(m.group(2)):
                notes.append(f"host-scan {m.group(0).strip()} -> cwd")
                return f"{m.group(1)} ."
            return m.group(0)

        def _ls(m: "re.Match") -> str:
            if self._outside(m.group(3)):
                notes.append(f"host-scan {m.group(0).strip()} -> cwd")
                return f"{m.group(1)}{m.group(2)} ."
            return m.group(0)

        out = re.sub(r"\b(find)\s+(/\S*)", _find, cmd)
        out = re.sub(r"\b(ls)((?:\s+-\S+)*)\s+(/\S*)", _ls, out)
        return out, notes

    def wrap_tool_call(self, request, handler):
        tc = request.tool_call
        if tc.get("name") == "execute":
            args = dict(tc.get("args") or {})
            cmd = args.get("command")
            if isinstance(cmd, str):
                new_cmd, notes = self._rewrite(cmd)
                if new_cmd != cmd:
                    args["command"] = new_cmd
                    logger.info("PathSafeExecute: rewrote virtual paths/host-scans %s", notes)
                    return handler(request.override(tool_call={**tc, "args": args}))
        return handler(request)


class EditRegroundMiddleware(AgentMiddleware):
    """Track file state for the model the way a coding harness would: when `edit_file`
    fails to match (the `old_string` is not in the live file, deepagents'
    occurrences-0 / not-unique cases), the model otherwise resubmits the same stale
    `old_string` indefinitely, because it reconstructs it from chat history polluted
    with old versions of the file. On a failed edit, re-ground the model in the
    file's current content and block the identical retry. Successful edits pass
    through untouched, and no other tool is affected."""

    _FAIL_MARKERS = ("String not found", "not unique", "appears ", "has not been read",
                     "read the file", "Error:")

    def __init__(self, run_dir, max_chars: int = 8000) -> None:
        super().__init__()
        self.run_dir = str(Path(run_dir).resolve())
        self.max_chars = int(max_chars)
        self._failed: set[tuple[str, str]] = set()   # (path, old_string) already failed

    def _resolve(self, file_path: str) -> Path:
        """Map a virtual leading-slash path (/scripts/x.jl) or relative path to the run dir."""
        return Path(self.run_dir) / file_path.lstrip("/")

    def _is_failure(self, msg: ToolMessage) -> bool:
        if getattr(msg, "status", None) == "error":
            return True
        content = msg.content if isinstance(msg.content, str) else ""
        return any(mk in content for mk in self._FAIL_MARKERS)

    def wrap_tool_call(self, request, handler):
        tc = request.tool_call
        if tc.get("name") != "edit_file":
            return handler(request)
        result = handler(request)
        # Only re-ground a ToolMessage failure (a Command short-circuit passes through).
        if not isinstance(result, ToolMessage) or not isinstance(result.content, str):
            return result
        if not self._is_failure(result):
            return result

        args = tc.get("args") or {}
        file_path = str(args.get("file_path", ""))
        old_string = str(args.get("old_string", ""))
        repeat = (file_path, old_string) in self._failed
        self._failed.add((file_path, old_string))

        try:
            text = self._resolve(file_path).read_text(encoding="utf-8", errors="replace")
            live = (text if len(text) <= self.max_chars else
                    text[: self.max_chars]
                    + f"\n...[truncated at {self.max_chars} chars; use read_file with offset/limit for the rest]")
        except Exception as exc:
            live = f"(could not read {file_path}: {exc})"

        repeat_note = ("\n\nYou ALREADY tried this exact edit and it failed; it WILL fail again. "
                       "Use the live content above or write_file." if repeat else "")
        guidance = (
            f"\n\n--- LIVE CONTENT of {file_path} (the source of truth; your old_string is NOT in it) ---\n"
            f"{live}\n--- end live content ---\n"
            f"Copy old_string VERBATIM from the live content above (exact whitespace, no line-number prefixes), "
            f"or replace the whole file with write_file. Do NOT resubmit the same old_string.{repeat_note}"
        )
        logger.info("EditReground: edit_file on %s failed to match; re-grounded with live content (repeat=%s)",
                    file_path, repeat)
        return ToolMessage(
            content=result.content + guidance,
            tool_call_id=result.tool_call_id,
            name=getattr(result, "name", "edit_file"),
            status="error",
        )


class HitlGateMiddleware(AgentMiddleware):
    """Human-in-the-loop order guard, registered only when HITL is on. So a checkpoint
    can't be silently skipped, block full DMRG runs (`run_julia_batch`, and `run_julia`
    with `fresh=True`) until the plan has been reviewed, i.e. until
    `request_plan_review` has written the `.plan_reviewed` sentinel. Cheap `fresh=False`
    REPL probes stay allowed, so the agent can still probe while drafting the plan.
    (`finish` self-guards on `.review_approved`; this middleware doesn't touch it.)"""

    def __init__(self, run_dir) -> None:
        super().__init__()
        self.run_dir = Path(run_dir)

    def wrap_tool_call(self, request, handler):
        tc = request.tool_call
        name = tc.get("name")
        if name in ("run_julia", "run_julia_batch"):
            args = tc.get("args") or {}
            is_full = (name == "run_julia_batch") or bool(args.get("fresh"))
            if is_full and not (self.run_dir / PLAN_REVIEWED).exists():
                logger.info("HitlGate: blocked %s, plan not yet reviewed.", name)
                return ToolMessage(
                    content=("Blocked: human plan-review is enabled. Call `request_plan_review` "
                             "(and incorporate the feedback) BEFORE running full DMRG. Cheap "
                             "`fresh=False` REPL probes are allowed in the meantime."),
                    tool_call_id=tc.get("id", ""),
                    name=name,
                    status="error",
                )
        return handler(request)


class SkillGateMiddleware(AgentMiddleware):
    """Make the load-bearing skills actually get read.

    The system prompt points at the skill library instead of restating it. That only
    works if the skills are opened, and prose instructions to read them are not enough
    on their own. So the four skills whose content prevents a silent wrong answer are
    gated here.

    Four design choices, each avoiding a bug this middleware could otherwise introduce:

    1. Fires once per skill, then releases. A speed bump, not a wall. If the path
       matching is ever wrong, the cost is one spurious error message rather than a
       deadlocked run; a permanently blocked `write_file` is exactly the kind of thing
       that sends the agent into an edit loop.
    2. "Has read" lives in instance state, not in the message history. Scanning
       messages breaks after summarization: the read_file call is compacted away, the
       flag silently resets, and the gate re-fires mid-run.
    3. Auto-disabled when skills are off. If skills are disabled and the gates stay
       on, a skill-free configuration becomes unrunnable.
    4. Main agent only. Subagents get their own middleware instances and their own
       history.
    """

    # An ED script is also a .jl file, and should ask for the ED skill rather than
    # the DMRG one, so matching is ordered most-specific-first.
    _JL = (".jl",)

    def __init__(self, run_dir, absent: "set[str] | None" = None) -> None:
        super().__init__()
        self.run_dir = Path(run_dir)
        self._read: set[str] = set()      # skills seen (monotonic, never shrinks)
        self._fired: set[str] = set()      # gates already raised once (never re-raise)
        # Skills not loaded for this run (agent.skills_exclude). A gate demanding a skill the
        # agent cannot open would block that tool forever: the agent is told to read a file
        # that is not in its filesystem, can never satisfy the gate, and the run stalls. A
        # configuration that drops a skill has to drop its gate with it.
        self._absent: set[str] = set(absent or ())

    def _skill_for(self, name: str, args: dict) -> str | None:
        """Which skill this call requires, or None.

        Writing Julia requires two skills, and the order matters: rule N1 is
        "convention before code", so `model-setup` (which fixes the operator
        convention, the sector and the geometry) has to come before the file is
        written, not after the first run. Gating it only on `run_julia` produced
        exactly the inverse: write the Hamiltonian, then be told to go decide what
        the Hamiltonian is.

        Since this returns a single skill, it returns `model-setup` while that is
        still unread and the code skill afterwards. Each gate fires once, so the cost
        of the two-step is one extra message, and the enforced order matches N1.
        """
        if name in ("run_julia", "run_julia_batch"):
            is_full = (name == "run_julia_batch") or bool(args.get("fresh"))
            return "model-setup" if is_full else None
        if name in ("write_file", "edit_file"):
            fp = str(args.get("file_path", ""))
            if not fp.endswith(SkillGateMiddleware._JL):
                return None
            if "model-setup" not in self._read:
                return "model-setup"          # N1: convention before code
            base = fp.rsplit("/", 1)[-1]
            return "ed-validation" if base.startswith("ed_") else "itensor-dmrg"
        if name == "finish":
            return "reporting"
        return None

    def _note_reads(self, tc: dict) -> None:
        """Record any skill whose SKILL.md this call opened."""
        if tc.get("name") not in ("read_file", "execute"):
            return
        blob = str(tc.get("args") or {})
        for skill in ("model-setup", "ed-validation", "itensor-dmrg", "reporting",
                      "observables", "phase-id", "transitions", "scaling", "disorder"):
            if f"skills/{skill}" in blob:
                self._read.add(skill)

    def wrap_tool_call(self, request, handler):
        tc = request.tool_call or {}
        self._note_reads(tc)

        name = tc.get("name")
        args = tc.get("args") or {}
        skill = self._skill_for(name, args)
        # `self._absent`: never gate on a skill this run does not have (agent.skills_exclude).
        # The agent could not open it, so the gate would block the tool permanently instead
        # of once.
        if skill is None or skill in self._read or skill in self._fired or skill in self._absent:
            return handler(request)

        self._fired.add(skill)            # constraint 1: this gate never raises again
        logger.info("SkillGate: blocked %s once, %s not yet read.", name, skill)
        return ToolMessage(
            content=(
                f"Blocked once: read `skills/{skill}/SKILL.md` before this step. It carries the "
                f"checks that stop this part of the study going silently wrong. Open it with "
                f"read_file (pass limit=1000), then repeat this call. This gate does not fire again."
            ),
            tool_call_id=tc.get("id", ""),
            name=name or "",
            status="error",
        )


class SubagentLogMiddleware(AgentMiddleware):
    """Persist every subagent call, prompt and final reply, to `logs/subagents.jsonl`.

    A subagent's returned text is not stored anywhere else the run keeps: the tool
    result recorded in `interactions.jsonl` is typically the literal string "OK", so
    without this record a reviewer can see that a subagent was invoked but not what
    it was asked or what it returned.

    So this records, per subagent call: which subagent, the exact prompt it was
    handed, its full reply, and (for the physics-critic) the parsed PASS/BLOCKER
    verdict. That makes the delegation traceable after the fact.

    Two artifacts:
      logs/subagents.jsonl   one line per call: type, prompt, reply, verdict, chars, n
      logs/verdicts.jsonl    the critic-only subset, for verdict-level analysis

    Observational only: it never blocks or alters a call.
    """

    _VERDICT_RE = re.compile(r"VERDICT:\s*(PASS|BLOCKER)", re.I)

    def __init__(self, run_dir) -> None:
        super().__init__()
        self.run_dir = Path(run_dir)
        self._n = 0

    @staticmethod
    def _result_text(result) -> str:
        """Pull the subagent's reply text out of whatever the task tool returned.

        deepagents' task tool returns a Command, not a ToolMessage:
            Command(update={..., "messages": [ToolMessage(content, ...)]})
        so a plain `result.content` reads as empty even when the subagent produced
        a long reply. Handle both shapes.
        """
        text = getattr(result, "content", None)
        if isinstance(text, str) and text.strip():
            return text
        update = getattr(result, "update", None)          # Command
        if isinstance(update, dict):
            msgs = update.get("messages") or []
            for m in reversed(msgs):                      # last message carries the reply
                c = getattr(m, "content", None)
                if isinstance(c, str) and c.strip():
                    return c
                if isinstance(c, list):                   # content blocks
                    parts = [b.get("text", "") for b in c if isinstance(b, dict)]
                    if any(parts):
                        return "\n".join(parts)
        return ""

    def _append(self, name: str, rec: dict) -> None:
        p = self.run_dir / "logs" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    def wrap_tool_call(self, request, handler):
        result = handler(request)
        try:
            tc = request.tool_call or {}
            if tc.get("name") != "task":           # only the subagent-spawning tool
                return result
            args = tc.get("args") or {}
            subagent = args.get("subagent_type") or "general-purpose"
            text = self._result_text(result)
            verdict = None
            if subagent == "physics-critic":
                m = self._VERDICT_RE.search(text)
                verdict = m.group(1).upper() if m else None
            self._n += 1
            rec = {
                "n": self._n,
                "subagent": subagent,
                "prompt": str(args.get("description") or args.get("prompt") or "")[:8000],
                "reply": text[:20000],
                "chars": len(text),
                "verdict": verdict,
            }
            self._append("subagents.jsonl", rec)
            # Keep the critic-only file so verdict-level tooling has a stable input.
            if subagent == "physics-critic":
                self._append("verdicts.jsonl", {
                    "n": self._n, "verdict": verdict, "chars": len(text),
                    "text": rec["reply"], "prompt": rec["prompt"][:2000],
                })
        except Exception:                          # never let logging break a run
            logger.debug("SubagentLog: could not record a subagent call", exc_info=True)
        return result


# Alias kept for external tooling that referenced the old name.
VerdictLogMiddleware = SubagentLogMiddleware


def _register_safety_profile(model: BaseChatModel, cfg: dict[str, Any]) -> bool:
    """Attach the crash guards to every agent by registering them on the harness profile.

    Why a profile rather than middleware.append(): deepagents auto-creates a
    `general-purpose` subagent with its own hardcoded middleware list, and per-agent
    appends never reach it. A harness profile's `extra_middleware` is materialised into
    all three places (verified in the installed deepagents): the main agent, declared
    subagents, and the auto-added general-purpose subagent. Registering under the
    provider key relies on the documented provider-only fallback in
    `_harness_profile_for_model`, which is what a pre-built model instance resolves
    through since it carries no spec string.

    Two constraints, both enforced by the library:
      * `extra_middleware` takes instances. A class or a factory lambda raises
        AttributeError inside langchain's agent factory.
      * The per-agent appends must be removed. Supplying a guard by both routes raises
        "AssertionError: Please remove duplicate middleware instances."

    Vision gate: only language-only models need the image guard, so it is skipped when
    the model can actually see images (`llm.vision: true` declares that). The default
    is off (guard on) deliberately: a text-only model that receives an image returns an
    unrecoverable 400, so a new provider is safe by default.

    ContextOverflowClassifier is registered here for the same reach: vLLM phrases a
    context overflow as "This model's maximum context length is ... tokens", which
    langchain_openai does not recognise, so the raw 400 would escape instead of being
    reclassified into ContextOverflowError where deepagents' own trim-and-retry
    recovery catches it. It is not gated on vision: a context overflow is possible on
    any model.

    ToolErrorGuard is registered here too, and is the broadest of the three: langgraph
    re-raises any tool exception that is not a ToolException, so a malformed tool
    argument would otherwise end the whole study. See qme/tool_error_guard.py for what
    it deliberately does not catch; that exclusion list is load-bearing.

    Returns True when the profile was registered.
    """
    guards: list[AgentMiddleware] = [ContextOverflowClassifier(), ToolErrorGuard()]
    if not cfg.get("llm", {}).get("vision", False):
        guards.append(ImageReadGuard())
    try:
        from deepagents.profiles import register_harness_profile
        from deepagents.profiles.harness.harness_profiles import HarnessProfile
        provider = (model._get_ls_params() or {}).get("ls_provider")
    except Exception:
        logger.warning("safety profile: could not resolve harness profile, guards NOT installed")
        return False
    if not provider:
        logger.warning("safety profile: model exposes no ls_provider, guards NOT installed")
        return False
    register_harness_profile(provider, HarnessProfile(extra_middleware=guards))
    logger.info("safety profile registered for provider %r: %s "
                "(covers main agent, declared subagents, and general-purpose)",
                provider, [type(g).__name__ for g in guards])
    return True


def build_agent(cfg: dict[str, Any], run_dir, model: BaseChatModel):
    """Construct and return the compiled deep agent + its checkpointer."""
    agent_cfg = cfg.get("agent", {}) or {}
    ctx = context_length(cfg)
    # headroom < 1.0 makes summarization fire proactively before a token undercount can
    # overflow the window; the ContextOverflowClassifier is the reactive backstop for
    # when it slips through anyway.
    set_summarization_profile(model, ctx,
                              headroom=float(agent_cfg.get("summary_headroom", 0.85)),
                              absolute=int(agent_cfg.get("max_input_tokens", 0) or 0))
    hitl_on = bool(agent_cfg.get("human_in_the_loop", False))

    # Rate-limit retry: off unless the config asks for it. `agent.rate_limit_retry: N`
    # enables it with N attempts per model call; 0 or absent means disabled, and a 429
    # fails the run as before. Off by default because a misconfigured limit would turn a
    # fast, loud failure into a silent multi-minute stall. See qme/rate_limit.py.
    _rate_limit_attempts = int(agent_cfg.get("rate_limit_retry", 0) or 0)

    # Proactive token budget: also off unless asked for. `agent.tokens_per_minute: N`
    # throttles model calls so the rolling 60 s window never knowingly exceeds N tokens.
    # Set it somewhat below the provider's real cap: the pre-call figure is an estimate,
    # and the quota is shared with anything else on the same API key. Keyed on the model
    # name so two different models do not draw down one shared budget; every agent in
    # this process (main, critic, analyst) shares the limiter for a given model, which
    # is what the provider actually meters.
    _tpm = int(agent_cfg.get("tokens_per_minute", 0) or 0)
    _tpm_key = str((resolve_agent_provider(cfg.get("llm", {}) or {}, "")[1] or {}).get("model", "default"))

    def _rate_limit_mw() -> list[AgentMiddleware]:
        """Rate-limit middleware, outermost-first. The retry must wrap the limiter, so
        that a retried attempt is throttled too; the other order would let the retry
        loop fire calls straight past the budget."""
        mw: list[AgentMiddleware] = []
        if _rate_limit_attempts:
            mw.append(RateLimitRetryMiddleware(max_attempts=_rate_limit_attempts))
        if _tpm:
            mw.append(TokenRateLimitMiddleware(limit=_tpm, key=_tpm_key))
        return mw

    backend = LocalShellBackend(root_dir=str(run_dir), virtual_mode=True)

    # run_python carries the same class of guards as run_julia (memory cap, timeout,
    # process-group kill), so agent Python never goes through an unguarded shell where
    # a runaway plotting script could hold the machine's RAM indefinitely.
    tools = [run_julia, run_julia_batch, run_python, validate, lookup_doc, update_run_summary, finish]
    if hitl_on:  # human-in-the-loop checkpoints (only registered when on)
        tools += [request_plan_review, request_review]

    # Subagents get the same behavioral path-safety as the main agent. `create_deep_agent`
    # prepends the base subagent stack (TodoList + Filesystem file/execute tools +
    # summarization + PatchToolCalls) and appends our `middleware`, so adding these keeps
    # the subagent's file/execute access and gives it the path rewrite as well. Fresh
    # instances per subagent (EditReground holds per-run state). Summarization is already
    # auto-injected for subagents, so it is not added here.
    def _subagent_safety_mw() -> list[AgentMiddleware]:
        mw: list[AgentMiddleware] = []
        if agent_cfg.get("enable_path_guard", True):
            mw.append(PathSafeExecuteMiddleware(run_dir))
        if agent_cfg.get("enable_edit_reground", True):
            mw.append(EditRegroundMiddleware(run_dir))
        # Subagents draw on the same per-organisation rate limit as the main agent, so a
        # 429 can land on the physics critic just as easily. Without this the critic's
        # call would raise and kill the run even though the main agent was protected.
        mw.extend(_rate_limit_mw())
        # The context-overflow classifier and the image guard are not appended here.
        # They are registered once on the harness profile instead, which is the only
        # route that also reaches the auto-added general-purpose subagent; supplying
        # them by both routes raises "Please remove duplicate middleware instances".
        return mw

    subagents: list[dict] = []
    if agent_cfg.get("enable_data_analyst", True):
        subagents.append({
            "name": "data-analyst",
            "description": DATA_ANALYST_DESCRIPTION,
            "system_prompt": DATA_ANALYST_PROMPT,
            # run_python plus the built-ins. Deliberately not run_julia: this subagent
            # must not be able to launch DMRG. What run_python does give it is a bounded
            # compute path (timeout, memory cap, output cap), so it can compute summaries
            # from data files instead of reading raw dumps into its context.
            "tools": [run_python],
            "middleware": _subagent_safety_mw(),
        })
    if agent_cfg.get("enable_physics_critic", True):
        subagents.append({
            "name": "physics-critic",
            "description": PHYSICS_CRITIC_DESCRIPTION,
            "system_prompt": PHYSICS_CRITIC_PROMPT,
            "tools": [run_python],   # reviews, doesn't run DMRG, but must be able to
                                     # compute: recomputing a claim from the stored data
                                     # is the whole point of the critic, and reading raw
                                     # data files into context instead is how a reviewer
                                     # blows its window.
            "middleware": _subagent_safety_mw(),
        })

    middleware: list[AgentMiddleware] = [create_summarization_tool_middleware(model, backend)]
    if agent_cfg.get("enable_nudges", True):
        middleware.append(IncrementalOutputNudge(
            run_dir,
            every_k=int(agent_cfg.get("nudge_every_k", 4)),
            loop_k=int(agent_cfg.get("nudge_loop_k", 6)),
            thrash_k=int(agent_cfg.get("nudge_thrash_k", 8)),
            summary_k=int(agent_cfg.get("nudge_summary_k", 6)),
        ))
    if agent_cfg.get("enable_path_guard", True):
        middleware.append(PathSafeExecuteMiddleware(run_dir))
    if agent_cfg.get("enable_edit_reground", True):
        middleware.append(EditRegroundMiddleware(run_dir))
    if hitl_on:  # guarantee the review checkpoints can't be silently skipped
        middleware.append(HitlGateMiddleware(run_dir))
    # The system prompt points at the skills instead of restating them, so the
    # load-bearing ones have to actually be opened. Auto-off when skills are disabled,
    # otherwise a skill-free configuration cannot run at all (see the class docstring).
    if agent_cfg.get("enable_skill_gate", True) and agent_cfg.get("enable_skills", True):
        # Which skills this run will not have (agent.skills_exclude, or all of them when
        # enable_skills is false). Computed here because the gate is constructed before
        # the skills list below, and a gate on a skill the agent cannot open blocks that
        # tool forever.
        _skill_gate_absent = {str(x).strip() for x in (agent_cfg.get("skills_exclude") or []) if str(x).strip()}
        if not agent_cfg.get("enable_skills", True):
            _skill_gate_absent = {p.name for p in _REPO_SKILLS.iterdir() if p.is_dir()}
        middleware.append(SkillGateMiddleware(run_dir, absent=_skill_gate_absent))
    # Always on (not gated on the critic): records every subagent call, prompt and
    # reply, to logs/subagents.jsonl, and the critic subset to logs/verdicts.jsonl.
    # Purely observational, and the only way a subagent's work survives the run; the
    # tool result otherwise logged is just "OK". The general-purpose subagent runs even
    # when the critic is disabled, so gating this on enable_physics_critic would lose
    # exactly the delegation most worth tracing.
    middleware.append(SubagentLogMiddleware(run_dir))

    # Wait out a provider rate limit (429) instead of dying on it. Disabled unless
    # `agent.rate_limit_retry: N` is set. These catch disjoint errors from the overflow
    # classifier: a rate limit here, a context overflow there, so both recoveries stay
    # reachable. See qme/rate_limit.py for why the openai SDK's own max_retries cannot
    # cover a rolling-minute token window on its own.
    middleware.extend(_rate_limit_mw())

    # Register the crash guards (context-overflow classifier, tool-error guard, and,
    # for non-vision models, the image-read guard) on the harness profile, so they
    # reach the main agent, the declared subagents, and the auto-added general-purpose
    # subagent alike. deepagents multimodal-encodes any image the agent reads, so a
    # text-only endpoint 400s unrecoverably; the guard therefore defaults to on and a
    # provider must declare `llm.vision: true` to receive images.
    _register_safety_profile(model, cfg)

    # Skill library, with optional per-skill exclusion.
    #
    # `agent.skills_exclude: [itensor-dmrg]` drops named skills while keeping the rest,
    # which is useful when measuring what a single skill contributes. The existing
    # `enable_skills: false` is all-or-nothing. deepagents takes a list of skill
    # directories, so exclusion is just building that list from the real skills/ tree
    # minus the excluded names, rather than passing the parent directory.
    _excluded = {str(x).strip() for x in (agent_cfg.get("skills_exclude") or []) if str(x).strip()}
    if not agent_cfg.get("enable_skills", True):
        skills = None
    elif _excluded:
        _present = sorted(p.name for p in _REPO_SKILLS.iterdir()
                          if p.is_dir() and (p / "SKILL.md").exists() and p.name not in _excluded)
        skills = [f"/skills/{n}" for n in _present]
        _missing = _excluded - {p.name for p in _REPO_SKILLS.iterdir() if p.is_dir()}
        if _missing:                      # a typo here would silently exclude nothing
            raise ValueError(f"agent.skills_exclude names unknown skills: {sorted(_missing)}")
        logger.info("Skills excluded for this run: %s (kept %d)", sorted(_excluded), len(_present))
    else:
        skills = ["/skills"]

    # Gemma thinking activation. Config-driven via agent.thinking_mode (default on) and
    # applied only when the served model is a Gemma (never prepended for other model
    # families). The config flag alone is a no-op; this prepend is the actual activation.
    system_prompt = MAIN_SYSTEM_PROMPT
    if hitl_on:  # tell the agent about the two review checkpoints (only when on)
        system_prompt = system_prompt + HITL_PROMPT_SNIPPET
        logger.info("Human-in-the-loop ON: plan + final review checkpoints engaged.")
    if agent_cfg.get("thinking_mode", True) and _is_gemma(cfg):
        system_prompt = "<|think|>\n" + system_prompt
        logger.info("gemma thinking ON: prepended <|think|> to the system prompt.")

    # Note on the gpt-oss reasoning level: deliberately not handled here. vLLM renders
    # its own harmony system message and exposes the level as a request field,
    # `reasoning_effort`, which it writes into the structured slot via the official
    # harmony library. Text prepended to this system prompt would land in the
    # instructions section instead and not set that slot. The setting therefore lives
    # with the model, in llm.vllm.reasoning_effort, and is forwarded by
    # qme/llm/provider._build_vllm.

    checkpointer = InMemorySaver()
    agent = create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        subagents=subagents,
        skills=skills,
        backend=backend,
        middleware=middleware,
        checkpointer=checkpointer,
    )
    logger.info(
        "Deep agent built: ctx=%d, subagents=%s, skills=%s, tools=%s",
        ctx, [s["name"] for s in subagents], bool(skills),
        [getattr(t, "name", t) for t in tools],
    )
    return agent
