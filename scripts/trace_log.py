"""Agent run trace logger.

Every agent invocation optionally writes a structured JSON trace to
``outputs/traces/<timestamp>_<command>_<agent>.json``.  Traces are append-only;
existing files are never modified.  The directory is created lazily.

Traces record:
  command        — e.g. "compile", "ask", "research-collect"
  agent          — e.g. "claude", "codex", "gemini"
  prompt_path    — path to the rendered prompt file passed to the agent
  started_at     — ISO-8601 timestamp
  finished_at    — ISO-8601 timestamp
  duration_s     — wall-clock seconds (float)
  exit_code      — 0 on success, non-zero on failure

Usage (from other scripts):
    from trace_log import TraceContext
    with TraceContext("compile", "claude", prompt_path):
        subprocess.run(cmd, check=True)
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from types import TracebackType

from utils import ROOT, ensure_dir, now_stamp

TRACES_DIR = ROOT / "outputs" / "traces"


def _write_trace(
    command: str,
    agent: str,
    prompt_path: Path | None,
    started_at: dt.datetime,
    finished_at: dt.datetime,
    exit_code: int,
) -> None:
    """Write one trace JSON file; swallow errors so tracing never breaks a workflow."""
    try:
        ensure_dir(TRACES_DIR)
        duration_s = (finished_at - started_at).total_seconds()
        payload = {
            "command": command,
            "agent": agent,
            "prompt_path": str(prompt_path.relative_to(ROOT)) if prompt_path else None,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_s": round(duration_s, 2),
            "exit_code": exit_code,
        }
        safe_cmd = command.replace(" ", "-").replace("/", "_")
        safe_agent = agent or "unknown"
        filename = f"{now_stamp()}_{safe_cmd}_{safe_agent}.json"
        (TRACES_DIR / filename).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass  # tracing must never break the workflow it wraps


class TraceContext:
    """Context manager that records a start/finish trace for one agent run.

    Usage::

        with TraceContext("compile", "claude", prompt_path):
            subprocess.run(cmd, check=True)
    """

    def __init__(self, command: str, agent: str, prompt_path: Path | None = None) -> None:
        self.command = command
        self.agent = agent
        self.prompt_path = prompt_path
        self._started_at: dt.datetime | None = None
        self._exit_code = 0

    def __enter__(self) -> "TraceContext":
        self._started_at = dt.datetime.now().replace(microsecond=0)
        return self

    def set_exit_code(self, code: int) -> None:
        self._exit_code = code

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        finished_at = dt.datetime.now().replace(microsecond=0)
        if exc_type is not None:
            import subprocess
            self._exit_code = getattr(exc_val, "returncode", 1)
        _write_trace(
            self.command,
            self.agent,
            self.prompt_path,
            self._started_at or finished_at,
            finished_at,
            self._exit_code,
        )
        # Never suppress exceptions
        return None
