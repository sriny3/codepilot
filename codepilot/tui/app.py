"""CodePilot TUI — 4-panel dashboard with HITL approval gate."""
from __future__ import annotations

import asyncio
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.app import App, ComposeResult
from textual.containers import Grid
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Label, RichLog
from rich.text import Text as RichText

from codepilot.tui.widgets import ActiveTaskPanel, ApprovalPanel, IssuesPanel, _log_color

if TYPE_CHECKING:
    from collections.abc import Callable
    from codepilot.tui.hitl import HITLCoordinator


class NewTaskModal(ModalScreen[str | None]):
    """Fullscreen input modal for free-form task entry."""

    DEFAULT_CSS = """
    NewTaskModal {
        align: center middle;
    }
    NewTaskModal > Label {
        margin-bottom: 1;
    }
    NewTaskModal > Input {
        width: 60;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("Enter a free-form coding task:")
        yield Input(placeholder="e.g. Add a health-check endpoint to the API", id="new-task-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def on_key(self, event: Any) -> None:
        if event.key == "escape":
            self.dismiss(None)


class CodePilotApp(App[None]):
    """Terminal dashboard: 4 panels — issues, active task, logs, approval."""

    TITLE = "CodePilot"
    SUB_TITLE = "autonomous coding agent"

    CSS = """
    CodePilotApp {
        background: #0a0e14;
    }
    Grid {
        grid-size: 2 3;
        grid-rows: 1fr 3fr auto;
        height: 1fr;
    }
    IssuesPanel { height: 1fr; }
    ActiveTaskPanel { height: 1fr; }
    #event-log {
        column-span: 2;
        border: tall #1e2a38;
        background: #0f1923;
        color: #b2c2d2;
    }
    ApprovalPanel {
        column-span: 2;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("l", "toggle_log", "Toggle Log"),
        ("i", "new_task", "New Task"),
        ("s", "skip_issue", "Skip"),
    ]

    def __init__(self, *, max_log_lines: int = 1000, log_dir: "Path | str | None" = None) -> None:
        super().__init__()
        self._max_log_lines = max_log_lines
        self._hitl: "HITLCoordinator | None" = None
        self._on_ready: Callable[[], None] | None = None
        self._task_queue: asyncio.Queue[str] = asyncio.Queue()
        self._pipeline_log: "io.TextIOWrapper | None" = None
        # Index in RichLog.lines where the current pending heartbeat starts.
        # Set by _set_log_heartbeat, cleared when a permanent line is appended
        # or when the heartbeat is explicitly cleared.
        self._heartbeat_start_idx: int | None = None
        if log_dir is not None:
            log_path = Path(log_dir)
            log_path.mkdir(parents=True, exist_ok=True)
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            self._pipeline_log = open(  # noqa: WPS515
                log_path / f"pipeline-{date_str}.log",
                "a",
                encoding="utf-8",
                buffering=1,  # line-buffered
            )

    def on_mount(self) -> None:
        if self._on_ready is not None:
            self._on_ready()

    def on_unmount(self) -> None:
        if self._pipeline_log is not None:
            self._pipeline_log.close()

    def compose(self) -> ComposeResult:
        yield Header()
        with Grid():
            yield IssuesPanel()
            yield ActiveTaskPanel()
            yield RichLog(max_lines=self._max_log_lines, id="event-log", wrap=True, highlight=False, markup=False)
            yield ApprovalPanel()
        yield Footer()

    # ── Panel update helpers (thread-safe via call_from_thread) ──────────────

    def append_log(self, message: str, raw: str | None = None) -> None:
        log = self.query_one("#event-log", RichLog)
        # Permanent line — discard any pending heartbeat first so it doesn't
        # remain frozen above newer real activity.
        self._trim_pending_heartbeat(log)
        colored = RichText(message, style=_log_color(message))
        log.write(colored)
        if self._pipeline_log is not None:
            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
            self._pipeline_log.write(f"{ts} {raw if raw is not None else message}\n")

    def _trim_pending_heartbeat(self, log: RichLog) -> None:
        """Remove the current pending heartbeat line from the log, if any."""
        if self._heartbeat_start_idx is None:
            return
        try:
            if self._heartbeat_start_idx < len(log.lines):
                del log.lines[self._heartbeat_start_idx:]
                log.refresh()
        except Exception:
            pass
        self._heartbeat_start_idx = None

    def _set_log_heartbeat(self, text: str) -> None:
        """Render the heartbeat as the last line of the log, replacing any prior heartbeat."""
        log = self.query_one("#event-log", RichLog)
        self._trim_pending_heartbeat(log)
        if not text:
            return
        colored = RichText(text, style=_log_color(text))
        self._heartbeat_start_idx = len(log.lines)
        log.write(colored)

    def _safe_call(self, fn: Any, *args: Any) -> None:
        """call_from_thread that silently no-ops if app has already exited."""
        try:
            self.call_from_thread(fn, *args)
        except RuntimeError:
            pass

    def post_append_log(self, message: str, raw: str | None = None) -> None:
        self._safe_call(self.append_log, message, raw)

    def show_approval_panel(self, operation: str, details: dict[str, Any]) -> None:
        self.query_one(ApprovalPanel).show_operation(operation, details)

    def hide_approval_panel(self) -> None:
        self.query_one(ApprovalPanel).hide()

    def upsert_issue(self, issue_id: int, title: str, state: str) -> None:
        self.query_one(IssuesPanel).upsert_issue(issue_id, title, state)

    def post_upsert_issue(self, issue_id: int, title: str, state: str) -> None:
        self._safe_call(self.upsert_issue, issue_id, title, state)

    def update_active_task(
        self,
        issue_id: int,
        title: str,
        state: str,
        skill: str,
        retry: int,
        todos: list[str],
    ) -> None:
        self.query_one(ActiveTaskPanel).update_task(issue_id, title, state, skill, retry, todos)

    def post_update_active_task(
        self,
        issue_id: int,
        title: str,
        state: str,
        skill: str,
        retry: int,
        todos: list[str],
    ) -> None:
        self._safe_call(self.update_active_task, issue_id, title, state, skill, retry, todos)

    def update_heartbeat(self, text: str) -> None:
        self.query_one(ActiveTaskPanel).update_heartbeat(text)
        self._set_log_heartbeat(text)

    def post_heartbeat(self, text: str) -> None:
        self._safe_call(self.update_heartbeat, text)

    # ── HITL approval input ──────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "approval-input":
            return
        val = event.value.strip().lower()
        if val in ("a", "approve", "y", "yes"):
            approved = True
        elif val in ("r", "reject", "n", "no"):
            approved = False
        else:
            self.append_log(f"[approval] unknown response '{val}' — type approve or reject")
            return
        self.hide_approval_panel()
        if self._hitl is not None:
            self._hitl.resolve(approved=approved)

    # ── Keybinding actions ───────────────────────────────────────────────────

    def action_toggle_log(self) -> None:
        log = self.query_one("#event-log", RichLog)
        log.display = not log.display

    def action_new_task(self) -> None:
        def _on_result(task: str | None) -> None:
            if task:
                self.append_log(f"[Manual] Queued: {task}")
                self._task_queue.put_nowait(task)

        self.push_screen(NewTaskModal(), _on_result)

    def action_skip_issue(self) -> None:
        self.append_log("[s] Skip — not yet implemented")
