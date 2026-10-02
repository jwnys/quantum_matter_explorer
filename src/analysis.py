"""
src/analysis.py

Read-only toolkit to load and visualize a single deep-agent run's trajectory and
statistics: per-point `data/*.json`, plus deep-agent signals (tool timeline,
productive-vs-looping progress, nudge firings, and the actual physics result).

Reads the structured logs written by `StatsLogger` (`logs/stats.jsonl`) and
`InteractionLogger` (`logs/interactions.jsonl`), plus `data/*.json` and the note.

  loaders   : load_stats / load_interactions / load_data_points / load_todos
  summaries : run_overview / print_overview / tool_stats / agent_stats /
              common_errors / nudge_counts / todo_report
  plots     : plot_tokens_over_time / plot_context_over_time / plot_tool_usage / plot_tool_timeline /
              plot_time_split / plot_progress / plot_physics / plot_errors / plot_todos  (one Figure each)
  orchestr. : analyze_run(run_dir), which prints the overview and saves all plots + todos.txt

CLI:  python -m src.analysis <run_folder> [--out DIR]
"""

from __future__ import annotations

import ast
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


# --- paths / loading ---

_REPO_ROOT = Path(__file__).resolve().parent.parent   # repo root


def _run_path(run_dir: "str | Path") -> Path:
    """Resolve a run folder. Accepts an absolute/relative path OR a bare run name
    (`run_YYYYmmdd_HHMMSS`). A bare name is looked up under the repo's `output/`
    dir (regardless of cwd) so `analysis/` lands inside the existing run folder
    instead of a new `./run_.../` next to wherever you invoked it."""
    p = Path(run_dir).expanduser()
    if p.exists():
        return p
    # bare name (or relative miss) → try the repo output dir, then cwd's output/
    for cand in (_REPO_ROOT / "output" / p.name, Path("output") / p):
        if cand.exists():
            return cand.resolve()
    return p   # not found anywhere → return as-is (downstream reports empty/missing)


def _read_jsonl(path: Path) -> list[dict]:
    """Read JSON-Lines, tolerating a truncated final line (in-progress run)."""
    rows: list[dict] = []
    if not path.exists():
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def load_stats(run_dir: "str | Path") -> pd.DataFrame:
    """`logs/stats.jsonl` → DataFrame (one row per event: tool_call / llm_call)."""
    return pd.DataFrame(_read_jsonl(_run_path(run_dir) / "logs" / "stats.jsonl"))


def load_interactions(run_dir: "str | Path") -> pd.DataFrame:
    """`logs/interactions.jsonl` → DataFrame (roles: prompt/response/tool_call/tool_result/info/error)."""
    return pd.DataFrame(_read_jsonl(_run_path(run_dir) / "logs" / "interactions.jsonl"))


def load_data_points(run_dir: "str | Path") -> pd.DataFrame:
    """Every `data/*.json` DMRG output → DataFrame, one row per file. Keeps scalar
    fields (alpha, energy_per_site, dimerization, N, …), records each array's length,
    and the file mtime (for progress timing). Returns empty if no data yet."""
    rows: list[dict] = []
    ddir = _run_path(run_dir) / "data"
    if not ddir.exists():
        return pd.DataFrame()
    for p in sorted(ddir.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        row: dict[str, Any] = {"_file": p.name, "_mtime": p.stat().st_mtime}
        for k, v in d.items():
            if isinstance(v, (int, float, str, bool)):
                row[k] = v
            elif isinstance(v, list):
                row[f"{k}__len"] = len(v)
            elif isinstance(v, dict):
                # Promote nested scalar fields (e.g. `params: {alpha, J1, J2, L}`, or a
                # per-N `"N24": {...}` wrapper) so the scan parameter isn't lost when the
                # Julia scripts nest it. A top-level key of the same name always wins, and
                # among nested dicts the first occurrence wins. Array-valued nested dicts
                # (structure_factor, spin_correlation, ...) contribute nothing here, by design.
                for kk, vv in v.items():
                    if isinstance(vv, (int, float, str, bool)) and kk not in d and kk not in row:
                        row[kk] = vv
        rows.append(row)
    return pd.DataFrame(rows)


# --- todo-list evolution (write_todos) ---

_TODO_PAIR_RE = re.compile(r"'content':\s*'(.*?)',\s*'status':\s*'(\w+)'", re.DOTALL)


def _parse_ts(s: Any) -> "datetime | None":
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _parse_todos(content: str) -> list[tuple[str, str]]:
    """`"write_todos ← {'todos': [{'content','status'}, ...]}"` → [(content, status)].
    Tries `ast.literal_eval` (exact) and falls back to a regex for truncated lines."""
    i = content.find("{")
    if i >= 0:
        try:
            d = ast.literal_eval(content[i:])
            items = d.get("todos") if isinstance(d, dict) else None
            if items:
                return [(str(t.get("content", "")).strip(), str(t.get("status", "pending")))
                        for t in items if isinstance(t, dict)]
        except Exception:
            pass
    return [(c.strip(), s) for c, s in _TODO_PAIR_RE.findall(content)]


def load_todos(run_dir: "str | Path") -> list[dict]:
    """Chronological snapshots of the agent's task list, one per `write_todos` call in
    `logs/interactions.jsonl`. Each: {ts, elapsed_min, iteration, todos, n_total / n_done /
    n_in_progress / n_pending}. Returns [] if the agent never used write_todos."""
    inter = _read_jsonl(_run_path(run_dir) / "logs" / "interactions.jsonl")
    snaps: list[dict] = []
    t0 = None
    for r in inter:
        if r.get("tool") != "write_todos" or r.get("role") != "tool_call":
            continue
        todos = _parse_todos(str(r.get("content", "")))
        if not todos:
            continue
        ts = _parse_ts(r.get("timestamp"))
        if t0 is None:
            t0 = ts
        elapsed = ((ts - t0).total_seconds() / 60.0) if (ts and t0) else float(len(snaps))
        n = Counter(s for _, s in todos)
        snaps.append({"ts": ts, "elapsed_min": round(elapsed, 2), "iteration": r.get("iteration"),
                      "todos": todos, "n_total": len(todos), "n_done": n.get("completed", 0),
                      "n_in_progress": n.get("in_progress", 0), "n_pending": n.get("pending", 0)})
    return snaps


def _todo_lifecycle(snaps: list[dict]):
    """(order, life, end_min): unique todos in first-seen order, per-todo
    {first, start, done, last}, and the run's last elapsed minute."""
    order: list[str] = []
    life: dict[str, dict] = {}
    for s in snaps:
        for content, status in s["todos"]:
            e = life.get(content)
            if e is None:
                e = life[content] = {"first": s["elapsed_min"], "start": None, "done": None, "last": status}
                order.append(content)
            if status == "in_progress" and e["start"] is None:
                e["start"] = s["elapsed_min"]
            if status == "completed" and e["done"] is None:
                e["done"] = s["elapsed_min"]
            e["last"] = status
    end = snaps[-1]["elapsed_min"] if snaps else 0.0
    return order, life, end


def _as_stats(x: "str | Path | pd.DataFrame") -> pd.DataFrame:
    return x if isinstance(x, pd.DataFrame) else load_stats(x)


def _numsum(df: pd.DataFrame, col: str) -> float:
    if col in df.columns:
        return float(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())
    return 0.0


def _events(stats: pd.DataFrame, kind: str) -> pd.DataFrame:
    if stats.empty or "event" not in stats.columns:
        return stats.iloc[0:0]
    return stats[stats["event"] == kind]


def _note_text(run_dir: "str | Path") -> "str | None":
    p = _run_path(run_dir) / "note" / "research_note.md"
    if p.exists():
        try:
            return p.read_text(encoding="utf-8")
        except Exception:
            return None
    return None


# --- summaries ---

def run_overview(run_dir: "str | Path") -> dict:
    """High-level scalars: wall time, call counts, tokens, #data points / plots,
    summarizations, nudges fired, and whether the note reached the done-gate."""
    run_dir = _run_path(run_dir)
    stats = load_stats(run_dir)
    inter = load_interactions(run_dir)
    dp = load_data_points(run_dir)
    ov: dict[str, Any] = {"name": run_dir.name, "run_dir": str(run_dir)}

    if not stats.empty:
        if "t_elapsed_s" in stats.columns:
            ov["wall_time_min"] = round(float(pd.to_numeric(stats["t_elapsed_s"], errors="coerce").max() or 0) / 60.0, 1)
        if "event" in stats.columns:
            ev = stats["event"].value_counts().to_dict()
            ov["llm_calls"] = int(ev.get("llm_call", 0))
            ov["tool_calls"] = int(ev.get("tool_call", 0))
        llm = _events(stats, "llm_call")
        ov["input_tokens"] = int(_numsum(llm, "input_tokens"))
        ov["output_tokens"] = int(_numsum(llm, "output_tokens"))
        ov["total_tokens"] = int(_numsum(llm, "total_tokens"))
        # peak context-window usage over the run (the bloat signal, flags a run nearing the limit)
        if not llm.empty and "context_pct" in llm.columns:
            _cp = pd.to_numeric(llm["context_pct"], errors="coerce").max()
            ov["context_pct_max"] = round(float(_cp), 3) if pd.notna(_cp) else None
        tc = _events(stats, "tool_call")
        if not tc.empty and "tool" in tc.columns:
            ov["tool_breakdown"] = tc["tool"].value_counts().to_dict()
        # where wall-time went: LLM-call seconds vs tool-call seconds (see plot_time_split)
        ov["llm_time_s"] = round(_numsum(llm, "duration_s"), 1)
        ov["tool_time_s"] = round(_numsum(tc, "duration_s"), 1)

    ov["data_points"] = int(len(dp))
    # Count SVG, PNG and PDF: runs have saved figures in different formats (dense figures
    # moved to PNG because a vector heatmap can reach tens of MB), so globbing a single
    # extension under-counts.
    _plotdir = run_dir / "plots"
    ov["plots"] = sum(len(list(_plotdir.glob(f"*.{ext}"))) for ext in ("svg", "png", "pdf"))
    ch = list((run_dir / "conversation_history").glob("*.md"))
    ov["summarizations"] = sum(t.read_text(encoding="utf-8", errors="replace").count("## Summarized at") for t in ch)

    if not inter.empty and "role" in inter.columns:
        ov["error_events"] = int((inter["role"] == "error").sum())
    ov["nudges"] = nudge_counts(inter)

    note = _note_text(run_dir)
    if note is not None:
        low = note.lower()
        ov["note_bytes"] = len(note)
        ov["reached_done_gate"] = ("## phase diagram" in low) and ("## conclusion" in low)

    todos = load_todos(run_dir)
    if todos:
        order, life, _ = _todo_lifecycle(todos)
        ever_done = sum(1 for c in order if life[c]["done"] is not None)
        ov["todo_updates"] = len(todos)
        ov["todos_done"] = f"{ever_done}/{len(order)} unique tasks"
    return ov


def tool_stats(stats: "str | Path | pd.DataFrame") -> pd.DataFrame:
    """Per-tool: call count, failures (ok==False), total/mean duration."""
    tc = _events(_as_stats(stats), "tool_call")
    if tc.empty:
        return pd.DataFrame()
    rows = []
    for tool, sub in tc.groupby("tool"):
        dur = pd.to_numeric(sub.get("duration_s"), errors="coerce").fillna(0) if "duration_s" in sub.columns else pd.Series([0.0])
        fails = int((sub["ok"] == False).sum()) if "ok" in sub.columns else 0  # noqa: E712
        rows.append({"tool": tool, "calls": int(len(sub)), "failures": fails,
                     "total_s": round(float(dur.sum()), 1), "mean_s": round(float(dur.mean()), 2)})
    return pd.DataFrame(rows).sort_values("calls", ascending=False).reset_index(drop=True)


def agent_stats(stats: "str | Path | pd.DataFrame") -> pd.DataFrame:
    """Per-agent breakdown (main agent + any subagents the callback tagged):
    llm/tool calls, tokens, and LLM vs tool seconds."""
    stats = _as_stats(stats)
    if stats.empty or "event" not in stats.columns or "agent" not in stats.columns:
        return pd.DataFrame()
    rows = []
    for agent, sub in stats.groupby("agent"):
        llm = sub[sub["event"] == "llm_call"]
        tool = sub[sub["event"] == "tool_call"]
        rows.append({"agent": agent, "llm_calls": int(len(llm)), "tool_calls": int(len(tool)),
                     "total_tokens": int(_numsum(llm, "total_tokens")),
                     "llm_time_s": round(_numsum(llm, "duration_s"), 1),
                     "tool_time_s": round(_numsum(tool, "duration_s"), 1)})
    return pd.DataFrame(rows).sort_values("tool_calls", ascending=False).reset_index(drop=True)


_NUDGE_PATTERNS = {
    "loop (run_julia, no data)": "likely LOOPING",
    "thrash (edit w/o run)":     "without running it",
    "stale note":               "note/research_note.md was last",
    "stale RUN_SUMMARY":        "RUN_SUMMARY.md was last updated",
}


def nudge_counts(inter: "str | Path | pd.DataFrame") -> dict:
    """How many times each soft-enforcement nudge fired (approximate: counts the
    reminder phrases injected into the model prompt)."""
    df = inter if isinstance(inter, pd.DataFrame) else load_interactions(inter)
    out: dict[str, int] = {}
    if df.empty or "content" not in df.columns:
        return out
    # nudges land in the (system) prompt: one firing is roughly one new prompt carrying it
    text_rows = df.loc[df.get("role").isin(["prompt"]), "content"] if "role" in df.columns else df["content"]
    blob_counts = Counter()
    for c in text_rows:
        s = str(c)
        for label, pat in _NUDGE_PATTERNS.items():
            if pat in s:
                blob_counts[label] += 1
    return {k: v for k, v in blob_counts.items() if v}


_EXC_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*(?:Error|Exception))\b")


def _classify_error(text: str) -> str:
    text = str(text)
    m = _EXC_RE.search(text)
    if m:
        return m.group(1)
    # status=ERROR/TIMEOUT is the single-tool header, and "status": "ERROR"/"TIMEOUT" is the
    # run_julia_batch JSON manifest per-point form. Match both.
    for pat, label in ((r"world.?age", "Julia world-age"),
                       (r"timed out|TimeoutExpired|status=TIMEOUT|\"status\":\s*\"TIMEOUT\"", "run_julia timeout"),
                       (r"status=ERROR|\"status\":\s*\"ERROR\"", "run_julia error"),
                       (r"No such file", "missing file (path)"),
                       (r"UndefVar", "UndefVarError")):
        if re.search(pat, text, re.IGNORECASE):
            return label
    return (text.strip().splitlines() or ["error"])[0][:60]


def common_errors(run_dir: "str | Path", top: int = 15) -> pd.DataFrame:
    """Ranked error types from structured signals: interaction role=='error',
    failed tool_calls, and run_julia results whose header is ERROR/TIMEOUT."""
    cnt: Counter = Counter()
    inter = load_interactions(run_dir)
    if not inter.empty and "role" in inter.columns and "content" in inter.columns:
        for c in inter.loc[inter["role"] == "error", "content"]:
            cnt[_classify_error(c)] += 1
        # run_julia returns its error as a normal tool_result string (status=ERROR/TIMEOUT)
        for c in inter.loc[inter["role"] == "tool_result", "content"]:
            s = str(c)
            if "status=ERROR" in s or "status=TIMEOUT" in s:
                cnt[_classify_error(s)] += 1
    tc = _events(load_stats(run_dir), "tool_call")
    if not tc.empty and "ok" in tc.columns and "tool" in tc.columns:
        for tool in tc.loc[tc["ok"] == False, "tool"]:  # noqa: E712
            cnt[f"tool raised: {tool}"] += 1
    return pd.DataFrame([{"error": k, "count": v} for k, v in cnt.most_common(top)])


def todo_report(run_dir: "str | Path") -> str:
    """Human-readable evolution of the agent's `write_todos` list (also saved to
    `analysis/todos.txt`): update count, a per-task lifecycle table, and the final list."""
    snaps = load_todos(run_dir)
    if not snaps:
        return "No write_todos calls recorded for this run."
    mark = {"completed": "[x]", "in_progress": "[~]", "pending": "[ ]"}
    order, life, _ = _todo_lifecycle(snaps)
    ever_done = sum(1 for c in order if life[c]["done"] is not None)
    f = snaps[-1]
    span = f["elapsed_min"] - snaps[0]["elapsed_min"]
    out = [f"TODO EVOLUTION: {len(snaps)} updates over {span:.1f} min",
           f"{len(order)} unique tasks, {ever_done} reached 'completed'",
           f"final list: {f['n_done']}/{f['n_total']} done ({f['n_in_progress']} in-progress, {f['n_pending']} pending)",
           "", "LIFECYCLE (per task, keyed by text):"]
    for c in order:
        e = life[c]
        start = f"start@{e['start']:.0f}m" if e["start"] is not None else "-"
        done = f"done@{e['done']:.0f}m" if e["done"] is not None else "-"
        out.append(f"  {mark.get(e['last'], '[?]')} seen@{e['first']:.0f}m {start:>10} {done:>9}  {c[:80]}")
    out += ["", "FINAL LIST:"]
    out += [f"  {mark.get(s, '[?]')} {c}" for c, s in f["todos"]]
    return "\n".join(out)


def print_overview(run_dir: "str | Path") -> dict:
    run_dir = _run_path(run_dir)
    ov = run_overview(run_dir)
    bar = "=" * 66
    print(bar); print(f" DEEP-AGENT RUN OVERVIEW: {ov.get('name', '')}"); print(bar)
    for k in ("wall_time_min", "llm_calls", "tool_calls", "input_tokens", "output_tokens",
              "total_tokens", "context_pct_max", "data_points", "plots", "note_bytes", "summarizations",
              "error_events", "nudges", "todo_updates", "todos_done", "reached_done_gate",
              "tool_breakdown"):
        if k in ov:
            print(f"  {k:18s}: {ov[k]}")
    errs = common_errors(run_dir, top=8)
    if not errs.empty:
        print("\n  most common errors:")
        print("  " + errs.to_string(index=False).replace("\n", "\n  "))
    return ov


# --- plots (one Figure each) ---

def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _new_ax(ax, figsize=(8, 5)):
    plt = _plt()
    if ax is not None:
        return ax.figure, ax
    fig = plt.figure(figsize=figsize)
    return fig, fig.add_subplot(111)


def plot_tokens_over_time(stats: "str | Path | pd.DataFrame", ax=None):
    """Cumulative INPUT vs OUTPUT tokens over elapsed time (two lines). Input =
    prompt tokens (dominated by re-sending the growing context each call); output =
    what the model actually generated. Totals shown in the legend."""
    stats = _as_stats(stats)
    fig, ax = _new_ax(ax)
    llm = _events(stats, "llm_call")
    cols = set(llm.columns) if not llm.empty else set()
    if not llm.empty and "t_elapsed_s" in cols and ({"input_tokens", "output_tokens"} & cols):
        d = llm.assign(_t=pd.to_numeric(llm["t_elapsed_s"], errors="coerce") / 60.0,
                       _in=pd.to_numeric(llm.get("input_tokens"), errors="coerce").fillna(0),
                       _out=pd.to_numeric(llm.get("output_tokens"), errors="coerce").fillna(0)).sort_values("_t")
        ax.plot(d["_t"], d["_in"].cumsum(), color="#4c78a8", lw=2, label=f"input  (Σ {int(d['_in'].sum()):,})")
        ax.plot(d["_t"], d["_out"].cumsum(), color="#54a24b", lw=2, label=f"output (Σ {int(d['_out'].sum()):,})")
        ax.set_xlabel("elapsed (min)"); ax.set_ylabel("cumulative tokens"); ax.set_ylim(bottom=0)
        ax.set_title("Token spend over time (input vs output)"); ax.legend(loc="upper left", fontsize=8)
    return fig


def plot_context_over_time(stats: "str | Path | pd.DataFrame", ax=None, context_window: int | None = None):
    """Live context-window usage over the run: `input_tokens` (the prompt size) per
    LLM call vs elapsed time. The instantaneous context size, not cumulative spend.
    Shows the climb and the sawtooth drop at each summarization, and (via context_pct)
    how close it gets to the window limit (the bloat signal behind runaway loops)."""
    stats = _as_stats(stats)
    fig, ax = _new_ax(ax)
    llm = _events(stats, "llm_call")
    if llm.empty or "t_elapsed_s" not in llm.columns or "input_tokens" not in llm.columns:
        ax.text(0.5, 0.5, "no LLM token data yet", ha="center", va="center"); ax.set_axis_off()
        return fig
    d = llm.assign(_t=pd.to_numeric(llm["t_elapsed_s"], errors="coerce") / 60.0,
                   _in=pd.to_numeric(llm["input_tokens"], errors="coerce")
                   ).dropna(subset=["_t", "_in"]).sort_values("_t")
    if d.empty:
        ax.text(0.5, 0.5, "no input_tokens recorded", ha="center", va="center"); ax.set_axis_off()
        return fig
    # Derive the context window so the token axis and the 0.85 trigger share one
    # consistent scale (two independently scaled axes drift out of alignment).
    win = float(context_window) if context_window else None
    if not win and "context_pct" in d.columns:
        cp = pd.to_numeric(d["context_pct"], errors="coerce")
        ratio = d["_in"][cp > 0] / cp[cp > 0]
        if not ratio.empty:
            win = float(ratio.median())
    ax.plot(d["_t"], d["_in"], color="#4c78a8", lw=1.5, marker=".", ms=4, label="context (input tokens)")
    ax.set_xlabel("elapsed (min)"); ax.set_ylabel("input tokens (live context size)")
    ax.set_title("Context-window usage over time")
    if win and win > 0:
        ax.set_ylim(0, win)                       # token axis spans the full window
        ax.axhline(0.85 * win, color="#e45756", ls="--", lw=1.2, alpha=0.8,
                   label="summarization trigger (85%)")
        ax.text(0.99, 0.95, f"window {win/1000:.0f}k tok · peak {d['_in'].max()/win:.0%}",
                transform=ax.transAxes, ha="right", va="top", fontsize=8)
        ax2 = ax.twinx()                          # aligned right axis: 0..win tokens maps to 0..100%
        ax2.set_ylim(0, 100); ax2.set_ylabel("% of context window")
    else:
        ax.set_ylim(bottom=0)
    ax.legend(loc="upper left", fontsize=8)
    return fig


def plot_tool_usage(stats: "str | Path | pd.DataFrame", ax=None):
    """Tool call counts with failures highlighted."""
    df = tool_stats(stats)
    fig, ax = _new_ax(ax)
    if not df.empty:
        df = df.sort_values("calls")
        ax.barh(df["tool"], df["calls"], color="#4c78a8", label="calls")
        ax.barh(df["tool"], df["failures"], color="#e45756", label="failures")
        ax.set_xlabel("count"); ax.set_title("Tool usage"); ax.legend()
    return fig


def plot_tool_timeline(stats: "str | Path | pd.DataFrame", ax=None):
    """Each tool call as a point over elapsed time, y=tool. A long horizontal band
    of one tool (e.g. edit_file / run_julia) is a loop/thrash, exactly what this
    plot exists to spot at a glance."""
    tc = _events(_as_stats(stats), "tool_call")
    fig, ax = _new_ax(ax, figsize=(11, 4))
    if not tc.empty and "tool" in tc.columns:
        tools = list(tc["tool"].value_counts().index)  # busiest first
        yi = {t: i for i, t in enumerate(tools)}
        x = pd.to_numeric(tc.get("t_elapsed_s"), errors="coerce") / 60.0 if "t_elapsed_s" in tc.columns else pd.Series(range(len(tc)))
        y = [yi[t] for t in tc["tool"]]
        ax.scatter(x, y, c=y, cmap="tab10", s=14, alpha=0.8)
        ax.set_yticks(range(len(tools))); ax.set_yticklabels(tools)
        ax.set_xlabel("elapsed (min)"); ax.set_title("Tool-call timeline (bands = loops)")
    return fig


def plot_time_split(stats: "str | Path | pd.DataFrame", ax=None):
    """Where wall-time goes: seconds spent waiting on LLM calls vs running tool calls.
    Left panel: the total LLM-vs-tool split (seconds + %), annotated with wall-clock and how
    much of it those two account for (the remainder is orchestration / network idle / HITL waits).
    Right panel: cumulative LLM-time vs tool-time over elapsed minutes, which shows what dominates
    and when (e.g. long DMRG batches = tool-time steps, a context-bloated end-game = LLM-time climb).
    (With a single `ax` passed, draws just the totals bar.)"""
    stats = _as_stats(stats)
    plt = _plt()
    llm = _events(stats, "llm_call")
    tc = _events(stats, "tool_call")
    llm_s, tool_s = _numsum(llm, "duration_s"), _numsum(tc, "duration_s")
    total = llm_s + tool_s
    wall_s = float(pd.to_numeric(stats["t_elapsed_s"], errors="coerce").max() or 0) if "t_elapsed_s" in stats.columns else 0.0

    if ax is not None:
        fig, axes, two = ax.figure, [ax], False
    else:
        fig, _axarr = plt.subplots(1, 2, figsize=(13, 5)); axes, two = list(_axarr), True

    a0 = axes[0]
    if total > 0:
        a0.barh(["time"], [llm_s], color="#4c78a8", label=f"LLM   {llm_s:.0f}s ({llm_s / total:.0%})")
        a0.barh(["time"], [tool_s], left=[llm_s], color="#f0a202", label=f"tools {tool_s:.0f}s ({tool_s / total:.0%})")
        a0.set_xlabel("seconds"); a0.set_title("LLM vs tool time (total)")
        a0.legend(loc="lower right", fontsize=8)
        if wall_s > 0:
            a0.text(0.01, 0.95, f"wall {wall_s / 60:.0f} min · LLM+tool accounts for {total / wall_s:.0%}",
                    transform=a0.transAxes, ha="left", va="top", fontsize=8, color="#555")
    else:
        a0.text(0.5, 0.5, "no timing data yet", ha="center", va="center"); a0.set_axis_off()

    if not two:
        return fig

    a1 = axes[1]
    plotted = False
    if total > 0 and "t_elapsed_s" in stats.columns:
        def _cum(df, color, label):
            nonlocal plotted
            d = df.assign(_t=pd.to_numeric(df["t_elapsed_s"], errors="coerce") / 60.0,
                          _d=pd.to_numeric(df.get("duration_s"), errors="coerce").fillna(0)).dropna(subset=["_t"]).sort_values("_t")
            if not d.empty:
                a1.plot(d["_t"], d["_d"].cumsum(), color=color, lw=2, label=label); plotted = True
        _cum(llm, "#4c78a8", "LLM (cumulative s)")
        _cum(tc, "#f0a202", "tools (cumulative s)")
        a1.set_xlabel("elapsed (min)"); a1.set_ylabel("cumulative seconds"); a1.set_ylim(bottom=0)
        a1.set_title("Cumulative LLM vs tool time"); a1.legend(loc="upper left", fontsize=8)
    if not plotted:
        a1.text(0.5, 0.5, "no timing data yet", ha="center", va="center"); a1.set_axis_off()
    return fig


def plot_progress(run_dir: "str | Path", ax=None):
    """Productive-vs-spinning: cumulative `run_julia` calls vs cumulative `data/*.json`
    files over time. If run_julia climbs while data stays flat, the agent is looping
    without producing results."""
    run_dir = _run_path(run_dir)
    stats = load_stats(run_dir)
    dp = load_data_points(run_dir)
    fig, ax = _new_ax(ax)
    # wall-clock origin from the first stats event
    t0 = None
    if not stats.empty and "ts" in stats.columns:
        try:
            t0 = min(datetime.fromisoformat(str(t).replace("Z", "+00:00")) for t in stats["ts"].dropna())
        except Exception:
            t0 = None
    rj = _events(stats, "tool_call")
    # count both the single tool and the batch tool: a batched survey makes no `run_julia`
    # calls at all, so filtering to "run_julia" alone makes batched runs look like 0 progress.
    rj = rj[rj["tool"].isin(["run_julia", "run_julia_batch"])] if not rj.empty and "tool" in rj.columns else rj
    if not rj.empty and "t_elapsed_s" in rj.columns:
        x = (pd.to_numeric(rj["t_elapsed_s"], errors="coerce") / 60.0).sort_values()
        ax.plot(x.values, range(1, len(x) + 1), color="#e45756", lw=2, label="DMRG calls (run_julia + batch)")
    if not dp.empty and "_mtime" in dp.columns and t0 is not None:
        mt = sorted((datetime.fromtimestamp(m, t0.tzinfo) - t0).total_seconds() / 60.0 for m in dp["_mtime"])
        ax.plot(mt, range(1, len(mt) + 1), color="#54a24b", lw=2, marker="o", ms=3, label="data/*.json written")
    elif not dp.empty:
        ax.axhline(len(dp), color="#54a24b", ls="--", label=f"data files: {len(dp)}")
    ax.set_xlabel("elapsed (min)"); ax.set_ylabel("cumulative count")
    ax.set_title("Progress: DMRG calls vs data produced"); ax.legend(loc="upper left")
    return fig


def plot_physics(run_dir: "str | Path", ax=None):
    """The actual scientific result: scalar observables vs the scan parameter
    from `data/*.json`, energy/site and dimerization if present."""
    dp = load_data_points(run_dir)
    fig, ax = _new_ax(ax, figsize=(8, 5))
    xcol = next((c for c in ("alpha", "J2", "lambda", "delta", "g") if c in dp.columns), None)
    if dp.empty or xcol is None or "energy_per_site" not in dp.columns:
        ax.text(0.5, 0.5, "no scalar scan data yet", ha="center", va="center"); ax.set_axis_off()
        return fig
    d = dp.sort_values(xcol)
    ax.plot(d[xcol], pd.to_numeric(d["energy_per_site"], errors="coerce"), "o-", color="#4c78a8", label="energy/site")
    ax.set_xlabel(xcol); ax.set_ylabel("energy / site", color="#4c78a8")
    ax.set_title("Physics: observables vs scan parameter")
    if "dimerization" in d.columns:
        ax2 = ax.twinx()
        ax2.plot(d[xcol], pd.to_numeric(d["dimerization"], errors="coerce"), "s--", color="#e45756", label="dimerization")
        ax2.set_ylabel("dimerization", color="#e45756")
    return fig


def plot_errors(run_dir: "str | Path", ax=None):
    df = common_errors(run_dir, top=15)
    fig, ax = _new_ax(ax)
    if not df.empty:
        df = df.iloc[::-1]
        ax.barh(df["error"], df["count"], color="#e45756")
        ax.set_xlabel("count"); ax.set_title("Most common errors")
    else:
        ax.text(0.5, 0.5, "no errors recorded", ha="center", va="center"); ax.set_axis_off()
    return fig


def plot_todos(run_dir: "str | Path", ax=None):
    """Gantt-style lifecycle of the agent's todo list: one row per unique task, a bar from
    first-seen to completed (or run end), grey/amber/green by latest status, with markers
    for started and completed. Shows what got added, started, finished, or stalled."""
    snaps = load_todos(run_dir)
    order, life, end = _todo_lifecycle(snaps)
    fig, ax = _new_ax(ax, figsize=(11, min(14.0, max(3.0, 0.42 * (len(order) or 1)))))
    if not snaps:
        ax.text(0.5, 0.5, "no todos recorded", ha="center", va="center"); ax.set_axis_off()
        return fig
    colors = {"completed": "#54a24b", "in_progress": "#f0a202", "pending": "#9aa0a6"}
    for y, c in enumerate(order):
        e = life[c]
        x0, x1 = e["first"], (e["done"] if e["done"] is not None else end)
        ax.barh(y, max(x1 - x0, 0.05), left=x0, height=0.6, alpha=0.9,
                color=colors.get(e["last"], "#9aa0a6"), edgecolor="white")
        if e["start"] is not None:
            ax.plot(e["start"], y, "o", color="#b8860b", ms=5)
        if e["done"] is not None:
            ax.plot(e["done"], y, "D", color="#1e7d34", ms=5)
    ax.set_yticks(range(len(order))); ax.set_yticklabels([c[:60] for c in order], fontsize=7)
    ax.invert_yaxis()
    ax.set_xlabel("elapsed (min)")
    ax.set_title("Todo lifecycle (bar = seen to done, ● started, ◆ completed)")
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=colors[k], label=k) for k in ("completed", "in_progress", "pending")],
              fontsize=8, loc="lower right")
    return fig


# --- orchestrator ---

def analyze_run(run_dir: "str | Path", out_dir: "str | Path | None" = None, show: bool = False) -> dict:
    """Print the overview and build+save every plot to `<run>/analysis/`."""
    run_dir = _run_path(run_dir)
    out_dir = Path(out_dir) if out_dir else run_dir / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)

    print_overview(run_dir)
    stats = load_stats(run_dir)
    plt = _plt()
    plotters = {
        "tokens_over_time": lambda: plot_tokens_over_time(stats),
        "context_over_time": lambda: plot_context_over_time(stats),
        "tool_usage":       lambda: plot_tool_usage(stats),
        "tool_timeline":    lambda: plot_tool_timeline(stats),
        "time_split":       lambda: plot_time_split(stats),
        "progress":         lambda: plot_progress(run_dir),
        "physics":          lambda: plot_physics(run_dir),
        "errors":           lambda: plot_errors(run_dir),
        "todos":            lambda: plot_todos(run_dir),
    }
    results: dict[str, str] = {}
    for name, fn in plotters.items():
        try:
            fig = fn(); fig.tight_layout()
            p = out_dir / f"{name}.png"
            fig.savefig(p, dpi=120, bbox_inches="tight")
            results[name] = str(p)
            if not show:
                plt.close(fig)
        except Exception as exc:  # one bad plot must not kill the rest
            results[name] = f"(failed: {exc})"

    # todo-list evolution as a plain-text record alongside the plots
    try:
        (out_dir / "todos.txt").write_text(todo_report(run_dir), encoding="utf-8")
        results["todos.txt"] = str(out_dir / "todos.txt")
    except Exception as exc:
        results["todos.txt"] = f"(failed: {exc})"
    ok = sum(1 for k in plotters if not results.get(k, "(failed").startswith("(failed"))
    print(f"\nSaved {ok}/{len(plotters)} plots + todos.txt to {out_dir}")
    for name, val in results.items():
        if val.startswith("(failed"):
            print(f"  ! {name}: {val}")
    return results


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Analyze a deep-agent run folder's stats / trajectory.")
    ap.add_argument("run_dir", help="path to a run folder (the timestamped dir under output/)")
    ap.add_argument("--out", default=None, help="output dir for plots (default <run>/analysis/)")
    args = ap.parse_args()
    analyze_run(args.run_dir, out_dir=args.out)
