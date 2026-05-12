"""TUI panel widgets for the 4-panel CodePilot layout."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.color import Color
from textual.containers import Vertical
from textual.widgets import DataTable, Input, Static
from textual.widgets._data_table import CellDoesNotExist
from rich.text import Text as RichText

_STATE_ICON: dict[str, str] = {
    "TRIAGED": "●",
    "EXPLORING": "◌",
    "IMPLEMENTING": "◉",
    "TESTING": "◎",
    "PR_OPENED": "◈",
    "DONE": "✓",
    "FAILED": "✗",
}

_STATE_AGENT: dict[str, str] = {
    "TRIAGED": "Orchestrator",
    "EXPLORING": "RepoExplorer",
    "IMPLEMENTING": "Coder",
    "TESTING": "TestAgent",
    "PR_OPENED": "PRAgent",
    "DONE": "Orchestrator",
    "FAILED": "Orchestrator",
}

_STATE_COLOR: dict[str, str] = {
    "TRIAGED": "#5c6370",
    "EXPLORING": "#4a9eff",
    "IMPLEMENTING": "#e5c07b",
    "TESTING": "#c678dd",
    "PR_OPENED": "#56b6c2",
    "DONE": "#5cb85c",
    "FAILED": "#e06c75",
}


def _log_color(message: str) -> str:
    """Pick a display color for a log line based on keywords."""
    msg = message.lower()
    if any(k in msg for k in ("failed", "error", "✗")):
        return "#e06c75"
    if any(k in msg for k in ("done", "✓", "success", "merged")):
        return "#5cb85c"
    if any(k in msg for k in ("working", "warn")):
        return "#e5c07b"
    return "#b2c2d2"


class IssuesPanel(Vertical):
    """Top-left: live feed of polled GitHub issues."""

    DEFAULT_CSS = """
    IssuesPanel {
        border: tall #1e2a38;
        height: 1fr;
        background: #0f1923;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("GitHub Issues", classes="panel-title")
        yield DataTable(id="issues-table", show_header=False, show_cursor=True)

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("issue", key="issue")

    def upsert_issue(self, issue_id: int, title: str, state: str) -> None:
        table = self.query_one(DataTable)
        key = str(issue_id)
        color = _STATE_COLOR.get(state, "#5c6370")
        icon = _STATE_ICON.get(state, "●")
        short_title = title[:28]
        cell = RichText(f"{icon} #{issue_id} {short_title}", style=color)
        try:
            table.update_cell(key, "issue", cell)
        except CellDoesNotExist:
            table.add_row(cell, key=key)


class ActiveTaskPanel(Vertical):
    """Top-right: current task state, agent, skill, retry, heartbeat."""

    DEFAULT_CSS = """
    ActiveTaskPanel {
        border: tall #1e2a38;
        height: 1fr;
        background: #0f1923;
        color: #b2c2d2;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("Active Task", id="task-header")
        yield Static("", id="task-state")
        yield Static("", id="task-agent-name")
        yield Static("", id="task-skill")
        yield Static("", id="task-retry")
        yield Static("", id="task-heartbeat")

    def update_task(
        self,
        issue_id: int,
        title: str,
        state: str,
        skill: str,
        retry: int,
        todos: list[str] | None = None,
    ) -> None:
        color = _STATE_COLOR.get(state, "#5c6370")
        icon = _STATE_ICON.get(state, "●")
        agent = _STATE_AGENT.get(state, "Orchestrator")
        header = f"Issue #{issue_id}" + (f": {title}" if title else "")
        self.query_one("#task-header", Static).update(header)
        self.query_one("#task-state", Static).update(
            RichText(f"{icon} {state}", style=color)
        )
        self.query_one("#task-agent-name", Static).update(f"Agent: {agent}")
        self.query_one("#task-skill", Static).update(f"Skill: {skill}" if skill else "")
        self.query_one("#task-retry", Static).update(f"Retry: {retry}/3")
        self.query_one("#task-heartbeat", Static).update("")
        self.styles.border_left = ("tall", Color.parse(color))

    def update_heartbeat(self, text: str) -> None:
        self.query_one("#task-heartbeat", Static).update(
            RichText(text, style="#e5c07b") if text else ""
        )


class ApprovalPanel(Vertical):
    """Bottom row (full-width): HITL gate — hidden until interrupt fires."""

    DEFAULT_CSS = """
    ApprovalPanel {
        border: tall #1e2a38;
        background: #0f1923;
        display: none;
    }
    ApprovalPanel.--visible {
        display: block;
        border: tall #5cb85c;
        background: #0a1a0a;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("Awaiting Approval", id="approval-title")
        yield Static("", id="approval-description")
        yield Input(placeholder="approve / reject", id="approval-input")

    def show_operation(self, operation: str, details: dict) -> None:
        self.add_class("--visible")
        self.query_one("#approval-title", Static).update(
            RichText(f"⚠ APPROVAL REQUIRED — {operation}", style="#5cb85c")
        )
        desc = details.get("value", operation)
        self.query_one("#approval-description", Static).update(
            f"{desc}\n[A] Approve   [R] Reject"
        )

    def hide(self) -> None:
        self.remove_class("--visible")
        self.query_one("#approval-input", Input).value = ""
