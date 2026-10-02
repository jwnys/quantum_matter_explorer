"""
src/obs/logger.py

Structured logger that records every prompt/response exchanged in the system.

Two outputs:
  1. JSON Lines file: machine-readable, one record per interaction.
  2. Plain text transcript: human-readable, colour-annotated via Rich.

Every record carries:
  - timestamp (ISO-8601 UTC)
  - agent name
  - role ("prompt" | "response" | "system" | "tool_call" | "tool_result" | "info")
  - content (string)
  - token_count (approximate)
  - iteration (orchestration loop counter)
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
import concurrent.futures
from pathlib import Path
from typing import Any

# Rich is optional, degrade gracefully if not installed
try:
    from rich.console import Console
    from rich.markup import escape
    from rich.panel import Panel
    from rich.text import Text
    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False

# Colour mapping per agent (Rich markup colours, unknown names fall back to white)
_AGENT_COLOURS: dict[str, str] = {
    "main":            "bold bright_magenta",
    "data-analyst":    "bold bright_cyan",
    "physics-critic":  "bold bright_yellow",
    "general-purpose": "bold green",
    "system":          "dim white",
}

_ROLE_COLOURS: dict[str, str] = {
    "prompt":      "dim",
    "response":    "bright_white",
    "system":      "italic dim",
    "tool_call":   "yellow",
    "tool_result": "green",
    "info":        "blue",
    "error":       "bold red",
}


class InteractionLogger:
    """
    Singleton-style logger that every agent calls to record interactions.

    Usage:
        logger = InteractionLogger.get()
        logger.log(agent="main", role="prompt", content="...", iteration=3)
    """

    _instance: "InteractionLogger | None" = None

    def __init__(self, cfg: dict[str, Any]) -> None:
        log_dir   = Path(cfg.get("log_dir", "./output/logs"))
        log_dir.mkdir(parents=True, exist_ok=True)

        self._jsonl_path = log_dir / cfg.get("jsonl_file", "interactions.jsonl")
        self._text_path  = log_dir / cfg.get("text_file",  "transcript.txt")
        self._level      = getattr(logging, cfg.get("level", "DEBUG").upper(), logging.DEBUG)
        self._use_rich   = cfg.get("rich_console", True) and _RICH_AVAILABLE
        
        # Slack Webhook setup
        self._slack_webhook_url = cfg.get("slack_webhook_url")
        self._slack_truncate = cfg.get("slack_truncate", True)
        self._terminal_truncate = cfg.get("terminal_truncate", True)
        self._webhook_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1) if self._slack_webhook_url else None

        # Standard Python logger (also goes to stderr)
        self._py_logger = logging.getLogger("qme")
        self._py_logger.setLevel(self._level)
        if not self._py_logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(name)s] %(levelname)s - %(message)s"
            ))
            self._py_logger.addHandler(handler)

        # Rich console
        if self._use_rich:
            self._console = Console()

        # Open files in append mode (survives restarts)
        self._jsonl_fh = open(self._jsonl_path, "a", encoding="utf-8")
        self._text_fh  = open(self._text_path,  "a", encoding="utf-8")
        self._text_fh.write(
            f"\n\n{'='*80}\n"
            f"  SESSION START  {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
            f"{'='*80}\n\n"
        )
        self._text_fh.flush()

    # --- class-level convenience ---

    @classmethod
    def initialise(cls, cfg: dict[str, Any]) -> "InteractionLogger":
        cls._instance = cls(cfg)
        return cls._instance

    @classmethod
    def get(cls) -> "InteractionLogger":
        if cls._instance is None:
            # Fall back to a default instance with no file output
            cls._instance = cls({"log_dir": "./output/logs", "rich_console": False})
        return cls._instance

    # --- main API ---

    def log(
        self,
        agent: str,
        role: str,
        content: str,
        iteration: int = 0,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Record one interaction event."""
        record: dict[str, Any] = {
            "timestamp":   time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "iteration":   iteration,
            "agent":       agent,
            "role":        role,
            "content":     content,
            "approx_tokens": _approx_tokens(content),
        }
        if extra:
            record.update(extra)

        # JSON Lines
        self._jsonl_fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._jsonl_fh.flush()

        # Text transcript
        header = (
            f"[{record['timestamp']}] [{agent.upper()}] [{role.upper()}]"
            f"  (iter={iteration})\n"
        )
        self._text_fh.write(header + content + "\n\n" + "-"*60 + "\n\n")
        self._text_fh.flush()

        # Rich / plain console
        if self._use_rich:
            self._rich_print(agent, role, content, iteration, extra=extra)
        else:
            # Plain-text fallback: tool calls get a one-line announcement so
            # they're still visible without Rich.
            if role in ("tool_call", "tool_result") and extra and extra.get("tool"):
                arrow = ">" if role == "tool_call" else "<"
                tool_name = extra["tool"]
                head = (content.splitlines()[0] if content else "")[:160]
                self._py_logger.info(
                    "[iter %d] %s %s %s %s - %s",
                    iteration, arrow, agent, "->" if role == "tool_call" else "<-",
                    tool_name, head,
                )
            elif getattr(self, "_terminal_truncate", True):
                self._py_logger.debug("[%s|%s] %s", agent, role, content[:200])
            else:
                self._py_logger.debug("[%s|%s] %s", agent, role, content)

        # Slack Webhook (background thread)
        if self._slack_webhook_url and self._webhook_executor:
            self._webhook_executor.submit(
                self._send_slack_message, agent, role, content, iteration
            )

    def info(self, agent: str, message: str, iteration: int = 0) -> None:
        """Short informational line (not a prompt/response)."""
        self.log(agent=agent, role="info", content=message, iteration=iteration)

    def warning(self, agent: str, message: str, iteration: int = 0) -> None:
        self.log(agent=agent, role="info", content=f"[WARN] {message}", iteration=iteration)
        self._py_logger.warning("[%s] %s", agent, message)

    def error(self, agent: str, message: str, iteration: int = 0) -> None:
        self.log(agent=agent, role="error", content=message, iteration=iteration)
        self._py_logger.error("[%s] %s", agent, message)

    def close(self) -> None:
        self._jsonl_fh.close()
        self._text_fh.close()
        if hasattr(self, '_webhook_executor') and self._webhook_executor:
            self._webhook_executor.shutdown(wait=False)

    # --- internal ---

    def _send_slack_message(self, agent: str, role: str, content: str, iteration: int) -> None:
        if not self._slack_webhook_url:
            return
        try:
            import json
            import urllib.request
            import time
            
            if self._slack_truncate:
                display = content if len(content) <= 2500 else content[:2500] + "\n... [truncated]"
                chunks = [display]
            else:
                # Slack text limits: usually ~3000-4000 chars. We chunk at 3000.
                max_len = 3000
                chunks = [content[i:i+max_len] for i in range(0, len(content), max_len)]
            
            for i, chunk in enumerate(chunks):
                if len(chunks) > 1:
                    header = f"*[iter {iteration}] {agent.upper()} › {role} (Part {i+1}/{len(chunks)})*\n"
                else:
                    header = f"*[iter {iteration}] {agent.upper()} › {role}*\n"
                
                payload = {
                    "text": f"{header}```{chunk}```"
                }
                
                req = urllib.request.Request(
                    self._slack_webhook_url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    pass
                    
                if len(chunks) > 1:
                    time.sleep(0.5)  # slight delay to prevent rate-limiting by Slack
        except Exception as e:
            self._py_logger.debug("Failed to send Slack message: %s", e)

    def _rich_print(
        self,
        agent: str,
        role: str,
        content: str,
        iteration: int,
        extra: dict[str, Any] | None = None,
    ) -> None:
        agent_colour = _AGENT_COLOURS.get(agent, "white")
        role_colour  = _ROLE_COLOURS.get(role, "white")

        # Tool calls get distinctive rendering so they jump out in the log
        # stream: arrow + tool name in the title, yellow border for the
        # call, green border for the result.
        if role in ("tool_call", "tool_result") and extra and extra.get("tool"):
            tool_name = extra["tool"]
            if role == "tool_call":
                arrow = ">"
                border = "yellow"
                title_style = "bold yellow"
                heading = f"{arrow} TOOL CALL  {agent} -> {tool_name}"
            else:
                arrow = "<"
                border = "green"
                title_style = "bold green"
                heading = f"{arrow} TOOL RESULT  {tool_name} -> {agent}"

            title = Text()
            title.append(f"[iter {iteration}] ", style="dim")
            title.append(heading, style=title_style)
            round_idx = extra.get("round")
            if round_idx is not None:
                title.append(f"  (round {round_idx})", style="dim")

            if getattr(self, "_terminal_truncate", True):
                display = content if len(content) <= 2000 else content[:2000] + "\n… [truncated]"
            else:
                display = content

            self._console.print(Panel(
                escape(display) if display.strip() else escape("(empty)"),
                title=title,
                title_align="left",
                border_style=border,
                padding=(0, 1),
            ))
            return

        # Default rendering (prompts, responses, info, errors)
        title = Text()
        title.append(f"[iter {iteration}] ", style="dim")
        title.append(agent.upper(), style=agent_colour)
        title.append(f" › {role}", style=role_colour)

        # Truncate very long content for the terminal if enabled
        if getattr(self, "_terminal_truncate", True):
            display = content if len(content) <= 2000 else content[:2000] + "\n… [truncated]"
        else:
            display = content

        self._console.print(Panel(
            escape(display),
            title=title,
            border_style=agent_colour.replace("bold ", ""),
            padding=(0, 1),
        ))


# --- helpers ---

def _approx_tokens(text: str) -> int:
    """Very rough token estimate (about 4 chars per token)."""
    return max(1, len(text) // 4)
