"""
src/tools/hitl.py

Optional human-in-the-loop: a simple blocking file gate with two checkpoints.

  - request_plan_review: pause after plan.md is drafted (checkpoint 1).
  - request_review:      pause when the study looks complete, before `finish` (checkpoint 2).

Each tool writes a fresh `HUMAN_REVIEW.md` in the run dir, notifies (banner + marker file +
optional webhook push), and blocks until the human flips `STATUS: PENDING` to `GO` (lenient).
It returns the human's freeform comments: empty means approve/proceed, non-empty means revise
(the agent re-calls the tool to re-present). The whole feature is off by default. When off,
these tools are not registered (see src/agent.py) and `finish` carries no guard.

Design notes:
  - nohup-compatible: the human interacts purely via files, no stdin/tty needed.
  - Detection re-reads and parses the file on each poll (no mtime/diff). Lines starting with
    '>' in the comments box are template hints and are ignored, so leaving the placeholder +
    GO reads as empty (no spurious revise loop).
  - On approval the gate writes a sentinel (.plan_reviewed / .review_approved) that
    HitlGateMiddleware + `finish` use to guarantee a checkpoint can't be silently skipped.

Env (set by main.py from config+CLI):
  QME_HITL              "1"/"0": whether HITL is on (read by `finish`'s guard)
  QME_HITL_TIMEOUT_MIN  minutes: auto-proceed after this, 0 = wait forever (default 720)
  QME_HITL_NOTIFY_URLS  comma-separated POST URLs (ntfy.sh topic / Slack webhook)
Run dir comes from QME_RUN_DIR (see sandbox.py).
"""

from __future__ import annotations

import os
import re
import time
import logging
from pathlib import Path

from langchain_core.tools import tool

from .sandbox import RUN_DIR

logger = logging.getLogger("qme.hitl")

REVIEW_FILE = "HUMAN_REVIEW.md"
MARKER_FILE = "ACTION_NEEDED"
PLAN_REVIEWED = ".plan_reviewed"
REVIEW_APPROVED = ".review_approved"

POLL_SECONDS = 4
DEFAULT_TIMEOUT_MIN = 720.0  # 12 h auto-proceed safety net

_STATUS_RE = re.compile(r"(?im)^\s*STATUS:\s*(\w+)")
_GO_TOKENS = {"GO", "PROCEED", "DONE"}
_COMMENTS_HEADER = "## Your comments"


# --- env helpers ---

def _timeout_min() -> float:
    try:
        return float(os.environ.get("QME_HITL_TIMEOUT_MIN", DEFAULT_TIMEOUT_MIN))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_MIN


def _notify_urls() -> list[str]:
    raw = os.environ.get("QME_HITL_NOTIFY_URLS", "")
    return [u.strip() for u in raw.split(",") if u.strip()]


# --- notification (fire-and-forget: never blocks, never raises) ---

def _notify(message: str) -> None:
    urls = _notify_urls()
    if not urls:
        return
    try:
        import httpx
    except Exception:  # pragma: no cover
        return
    for url in urls:
        try:
            if "hooks.slack.com" in url:
                httpx.post(url, json={"text": message}, timeout=4.0)
            else:  # ntfy.sh / generic: raw body
                httpx.post(url, content=message.encode("utf-8"), timeout=4.0)
        except Exception as exc:
            logger.debug("HITL notify failed for %s: %s", url, exc)


def _banner(message: str) -> None:
    """Print a prominent block to stdout, captured in nohup.out + logs/terminal.log."""
    bar = "=" * 76
    print(f"\n{bar}\n{message}\n{bar}\n", flush=True)


# --- review-file template + parsing ---

def _template(stage: str, run_dir: Path, summary: str) -> str:
    review_path = run_dir / REVIEW_FILE
    target = "plan.md" if stage == "PLAN" else "note/research_note.md"
    # Keep exactly one '## Your comments' header and one 'STATUS:' line in this file: the
    # instructional bullets deliberately avoid those literal strings so parsing can't be
    # fooled by decoy text (and a 'PENDING'->'GO' edit only ever hits the real status line).
    return (
        f"# Human review [waiting]: {stage} checkpoint   ·   run {run_dir.name}   ·   {review_path}\n"
        f"  - Review/edit:  open {target} (this folder), edit + save\n"
        f"  - Comment/ask:  write your notes under the 'Your comments' heading below (freeform)\n"
        f"  - When done:    change the bottom status line from PENDING to GO, and save (this resumes the run)\n"
        f"\n"
        f"Agent's note: {summary}\n"
        f"\n"
        f"{_COMMENTS_HEADER}\n"
        f"> (freeform. Leave empty to proceed as-is. Lines starting with '>' are hints and are ignored.)\n"
        f"\n"
        f"STATUS: PENDING\n"
    )


def _parse_status(text: str) -> str:
    m = _STATUS_RE.search(text)
    return m.group(1).upper() if m else "PENDING"


def _parse_comments(text: str) -> str:
    """Comments = text under '## Your comments' up to the STATUS line, with blank lines and
    '>'-prefixed hint lines (incl. the placeholder) dropped. A missing header means '' (proceed)."""
    start = text.find(_COMMENTS_HEADER)
    if start == -1:
        return ""
    body = text[start + len(_COMMENTS_HEADER):]
    m = _STATUS_RE.search(body)
    if m:
        body = body[: m.start()]
    lines = [ln.strip() for ln in body.splitlines()]
    real = [ln for ln in lines if ln and not ln.startswith(">")]
    return "\n".join(real).strip()


# --- the blocking gate ---

def _human_gate(stage: str, summary: str) -> str:
    """Write a fresh HUMAN_REVIEW.md, notify, and BLOCK until STATUS: GO (or timeout).
    Returns the human's comments ('' = approve/proceed)."""
    if RUN_DIR is None:
        logger.warning("HITL gate requested but QME_RUN_DIR unset, proceeding without review.")
        return ""
    run_dir = Path(RUN_DIR)
    review = run_dir / REVIEW_FILE
    marker = run_dir / MARKER_FILE

    review.write_text(_template(stage, run_dir, summary), encoding="utf-8")
    notice = (f"ACTION NEEDED: run {run_dir.name}, {stage} review. "
              f"Edit {review} and set STATUS: GO")
    try:
        marker.write_text(notice + "\n", encoding="utf-8")
    except Exception:
        pass
    _banner(notice)
    logger.info("HITL %s review requested: %s", stage, review)
    _notify(notice)

    timeout_min = _timeout_min()
    deadline = (time.time() + timeout_min * 60.0) if timeout_min > 0 else None
    while True:
        try:
            text = review.read_text(encoding="utf-8", errors="replace")
            status = _parse_status(text)
        except Exception:
            status, text = "PENDING", ""   # transient mid-save read, retry
        if status in _GO_TOKENS:
            comments = _parse_comments(text)
            _remove_marker(marker)
            logger.info("HITL %s review resumed (%s).", stage,
                        "with comments" if comments else "no comments, approve")
            return comments
        if deadline is not None and time.time() > deadline:
            _remove_marker(marker)
            msg = f"HITL {stage}: no response after {timeout_min:.0f} min, auto-proceeding."
            logger.warning(msg)
            _banner(msg)
            _notify(msg)
            return ""
        time.sleep(POLL_SECONDS)


def _remove_marker(marker: Path) -> None:
    try:
        marker.unlink(missing_ok=True)
    except Exception:
        pass


def _touch_sentinel(name: str) -> None:
    if RUN_DIR is None:
        return
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        (Path(RUN_DIR) / name).write_text(stamp + "\n", encoding="utf-8")
    except Exception:
        pass


# --- tools ---

@tool(parse_docstring=True)
def request_plan_review(summary: str) -> str:
    """Pause for a human to review/edit plan.md (human-in-the-loop checkpoint 1).

    Call this ONCE after you have drafted plan.md and gotten the physics-critic's plan
    review, and BEFORE running any full DMRG. A human reviews and may edit plan.md directly
    and/or leave comments; this returns their comments. EMPTY → proceed with the study.
    NON-EMPTY → re-read plan.md (they may have edited it), update it per their comments, and
    call this AGAIN (summary = what you changed) to re-present. Full DMRG runs are blocked
    until this review is approved; cheap fresh=False REPL probes stay allowed.

    Args:
        summary: One line describing what your plan proposes (shown to the human).
    """
    comments = _human_gate("PLAN", summary)
    if not comments:
        _touch_sentinel(PLAN_REVIEWED)
        return "Plan review APPROVED. Proceed with the study (run the survey / Phase-0 runs)."
    return (f"Human requested PLAN changes:\n{comments}\n\n"
            f"Re-read plan.md (they may also have edited it), update it accordingly, then call "
            f"request_plan_review again with summary='<what you changed>' to re-present for review.")


@tool(parse_docstring=True)
def request_review(summary: str) -> str:
    """Pause for a human to review the finished analysis (human-in-the-loop checkpoint 2).

    Call this when you believe the study is complete (note has Introduction … Phase diagram …
    Conclusion with embedded figures), INSTEAD of calling finish. A human reviews
    note/research_note.md and may leave comments. EMPTY → call finish(reason=...). NON-EMPTY →
    address every comment (update the note/figures) and call this AGAIN to re-present. `finish`
    is blocked until this review is approved.

    Args:
        summary: One line describing your headline result (shown to the human).
    """
    comments = _human_gate("FINAL", summary)
    if not comments:
        _touch_sentinel(REVIEW_APPROVED)
        return "Final review APPROVED. Now call finish(reason=...) to end the run."
    return (f"Human requested changes to the final analysis:\n{comments}\n\n"
            f"Address every point (update note/research_note.md + figures), then call "
            f"request_review again to re-present for review.")
