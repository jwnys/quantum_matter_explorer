"""
src/obs/stats_logger.py

Structured per-event metrics writer.

Each event is one line in `<run>/logs/stats.jsonl` (flat schema, easy to
load into pandas or a notebook for visualisation). The full-transcript
detail stays in `interactions.jsonl`, written separately.

Event types:
  - tool_call: one record per tool invocation
  - llm_call:  one record per `BaseChatModel.invoke()` call
  - agent_run: one record per agent turn (enter to leave)

Schema (every record has):
  ts            ISO-8601 UTC of the event
  t_elapsed_s   seconds since session start (process-monotonic)
  event         "tool_call" | "llm_call" | "agent_run"
  agent         the orchestrating agent name
  iteration     orchestration loop index

Event-specific fields:
  tool_call: tool, round, duration_s, ok, result_chars, args_keys, args_summary
  llm_call:  provider, model, duration_s, prompt_chars, response_chars,
             input_tokens, output_tokens, total_tokens
  agent_run: duration_s, phase_in, phase_out, ok

A single sidecar `stats.csv` is also written so the file can be opened
in a spreadsheet without preprocessing: same data, flattened, with
fields that do not apply to an event left blank.
"""

from __future__ import annotations

import csv
import json
import os
import time
from pathlib import Path
from typing import Any


class StatsLogger:
    """Singleton-style metric writer. `initialise(log_dir)` once at startup,
    `get()` anywhere afterwards."""

    _instance: "StatsLogger | None" = None

    # Columns kept in `stats.csv` (every event writes the same flat shape;
    # fields not relevant to the event type are left blank).
    _CSV_COLUMNS = [
        "ts", "t_elapsed_s", "event", "agent", "iteration",
        # tool_call
        "tool", "round", "ok", "result_chars", "args_keys", "args_summary",
        # llm_call
        "provider", "model", "prompt_chars", "response_chars",
        "input_tokens", "output_tokens", "total_tokens", "context_pct",
        # shared
        "duration_s",
        # agent_run
        "phase_in", "phase_out",
    ]

    def __init__(self, log_dir: str | Path) -> None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        self._jsonl_path = log_dir / "stats.jsonl"
        self._csv_path = log_dir / "stats.csv"

        self._jsonl_fh = open(self._jsonl_path, "a", encoding="utf-8")

        new_csv = not self._csv_path.exists() or self._csv_path.stat().st_size == 0
        self._csv_fh = open(self._csv_path, "a", encoding="utf-8", newline="")
        self._csv_writer = csv.DictWriter(
            self._csv_fh, fieldnames=self._CSV_COLUMNS, extrasaction="ignore",
        )
        if new_csv:
            self._csv_writer.writeheader()
            self._csv_fh.flush()

        self._wall_start = time.monotonic()
        self.context_window: int | None = None   # set via initialise(), enables context_pct on llm_call

    # --- public API ---

    @classmethod
    def initialise(cls, log_dir: str | Path, context_window: int | None = None) -> "StatsLogger":
        cls._instance = cls(log_dir)
        cls._instance.context_window = context_window
        return cls._instance

    @classmethod
    def get(cls) -> "StatsLogger":
        """Return the active StatsLogger, falling back to a no-op sink if
        nothing was initialised (so the wiring is safe to call from
        anywhere without crashing in scripts that don't set it up)."""
        if cls._instance is None:
            cls._instance = _NoopStatsLogger()
        return cls._instance

    def tool_call(
        self,
        *,
        agent: str,
        tool: str,
        iteration: int,
        round_idx: int,
        args: dict[str, Any] | Any,
        duration_s: float,
        ok: bool,
        result_chars: int,
    ) -> None:
        if isinstance(args, dict):
            keys = list(args.keys())
            summary = self._summarise_args(args)
        else:
            keys, summary = [], str(args)[:200]
        self._write({
            "event": "tool_call",
            "agent": agent, "iteration": iteration, "tool": tool,
            "round": round_idx, "duration_s": round(duration_s, 4),
            "ok": ok, "result_chars": int(result_chars),
            "args_keys": ",".join(keys),
            "args_summary": summary,
        })

    def llm_call(
        self,
        *,
        agent: str,
        iteration: int,
        provider: str,
        model: str,
        duration_s: float,
        prompt_chars: int,
        response_chars: int,
        input_tokens: int | None,
        output_tokens: int | None,
        total_tokens: int | None,
        forced_final: bool = False,
    ) -> None:
        """forced_final=True marks a bonus LLM call made after a tool loop
        exhausted its round budget without a terminal answer. Useful for
        post-hoc analysis: how often is the model failing to converge on
        its own?"""
        record = {
            "event": "llm_call",
            "agent": agent, "iteration": iteration,
            "provider": provider, "model": model,
            "duration_s": round(duration_s, 4),
            "prompt_chars": int(prompt_chars),
            "response_chars": int(response_chars),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            # fraction of the context window in use at this call (the running context-length signal).
            "context_pct": (round(input_tokens / self.context_window, 4)
                            if input_tokens and self.context_window else None),
        }
        if forced_final:
            record["forced_final"] = True
        self._write(record)

    def agent_run(
        self,
        *,
        agent: str,
        iteration: int,
        duration_s: float,
        phase_in: str,
        phase_out: str,
        ok: bool,
    ) -> None:
        self._write({
            "event": "agent_run",
            "agent": agent, "iteration": iteration,
            "duration_s": round(duration_s, 4),
            "phase_in": phase_in, "phase_out": phase_out, "ok": ok,
        })

    def close(self) -> None:
        try:
            self._jsonl_fh.close()
        except Exception:
            pass
        try:
            self._csv_fh.close()
        except Exception:
            pass

    # --- internals ---

    def _write(self, record: dict[str, Any]) -> None:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        t_elapsed_s = round(time.monotonic() - self._wall_start, 4)
        full = {"ts": ts, "t_elapsed_s": t_elapsed_s, **record}
        try:
            self._jsonl_fh.write(json.dumps(full, ensure_ascii=False, default=str) + "\n")
            self._jsonl_fh.flush()
        except Exception:
            pass
        try:
            self._csv_writer.writerow(full)
            self._csv_fh.flush()
        except Exception:
            pass

    @staticmethod
    def _summarise_args(args: dict[str, Any], max_chars: int = 160) -> str:
        """Render a dict of tool-call args as a short single-line summary:
        keys plus truncated values. Useful for the CSV column without dragging
        the full args body in there."""
        parts: list[str] = []
        for k, v in args.items():
            if isinstance(v, str):
                preview = v.replace("\n", " \\n ")
                if len(preview) > 40:
                    preview = preview[:40] + "…"
                parts.append(f"{k}={preview!r}")
            else:
                try:
                    rendered = json.dumps(v, ensure_ascii=False, default=str)
                except Exception:
                    rendered = str(v)
                if len(rendered) > 40:
                    rendered = rendered[:40] + "…"
                parts.append(f"{k}={rendered}")
        s = " ".join(parts)
        return s if len(s) <= max_chars else s[:max_chars] + "…"


class _NoopStatsLogger(StatsLogger):
    """Fallback used when nobody initialised the singleton: silently
    discards everything. Lets callers in tests or scripts call into the
    metric API without bootstrapping a real log directory."""

    def __init__(self) -> None:  # noqa: D401 (intentionally bypasses the parent)
        # Discard env: no files, no writer, no clock baseline.
        self._jsonl_fh = None
        self._csv_fh = None
        self._csv_writer = None
        self._wall_start = time.monotonic()

    def _write(self, record: dict[str, Any]) -> None:  # type: ignore[override]
        return

    def close(self) -> None:  # type: ignore[override]
        return
