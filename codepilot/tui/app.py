"""CodePilot TUI — 4-panel dashboard with HITL approval gate."""
from __future__ import annotations

from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Grid
from textual.widgets import Footer, Header, Log

from codepilot.tui.widgets import ActiveTaskPanel, ApprovalPanel, IssuesPanel


class CodePilotApp(App[None]):
    """Terminal dashboard: 4 panels — issues, active task, logs, approval."""

    TITLE = "CodePilot"
    SUB_TITLE = "autonomous coding agent"

    CSS = """
    Grid {
        grid-size: 2 2;
        height: 1fr;
    }
    IssuesPanel { height: 1fr; }
    ActiveTaskPanel { height: 1fr; }
    Log { height: 1fr; border: solid $panel; }
    ApprovalPanel { height: 1fr; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("l", "toggle_log", "Toggle Log"),
        ("i", "new_task", "New Task"),
        ("s", "skip_issue", "Skip"),
    ]

    def __init__(self, *, max_log_lines: int = 1000) -> None:
        super().__init__()
        self._max_log_lines = max_log_lines

    def compose(self) -> ComposeResult:
        yield Header()
        with Grid():
            yield IssuesPanel()
            yield ActiveTaskPanel()
            yield Log(max_lines=self._max_log_lines, id="event-log")
            yield ApprovalPanel()
        yield Footer()

    # ── Panel update helpers (thread-safe via call_from_thread) ──────────────

    def append_log(self, message: str) -> None:
        self.query_one("#event-log", Log).write_line(message)

    def post_append_log(self, message: str) -> None:
        self.call_from_thread(self.append_log, message)

    def show_approval_panel(self, operation: str, details: dict[str, Any]) -> None:
        self.query_one(ApprovalPanel).show_operation(operation, details)

    def hide_approval_panel(self) -> None:
        self.query_one(ApprovalPanel).hide()

    def upsert_issue(self, issue_id: int, title: str, state: str) -> None:
        self.query_one(IssuesPanel).upsert_issue(issue_id, title, state)

    def post_upsert_issue(self, issue_id: int, title: str, state: str) -> None:
        self.call_from_thread(self.upsert_issue, issue_id, title, state)

    def update_active_task(
        self,
        issue_id: int,
        state: str,
        skill: str,
        retry: int,
        todos: list[str],
    ) -> None:
        self.query_one(ActiveTaskPanel).update_task(issue_id, state, skill, retry, todos)

    def post_update_active_task(
        self,
        issue_id: int,
        state: str,
        skill: str,
        retry: int,
        todos: list[str],
    ) -> None:
        self.call_from_thread(self.update_active_task, issue_id, state, skill, retry, todos)

    # ── Keybinding actions ───────────────────────────────────────────────────

    def action_toggle_log(self) -> None:
        log = self.query_one("#event-log", Log)
        log.display = not log.display

    def action_new_task(self) -> None:
        self.append_log("[i] New task — free-form input not yet implemented")

    def action_skip_issue(self) -> None:
        self.append_log("[s] Skip — not yet implemented")
