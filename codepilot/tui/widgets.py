"""TUI panel widgets for the 4-panel CodePilot layout."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Input, ListView, Static
from textual.widgets._data_table import CellDoesNotExist


class IssuesPanel(Vertical):
    """Top-left: live feed of polled GitHub issues."""

    DEFAULT_CSS = """
    IssuesPanel {
        border: solid $panel;
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("Issues", classes="panel-title")
        yield DataTable(id="issues-table")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("#", key="num")
        table.add_column("Title", key="title")
        table.add_column("State", key="state")

    def upsert_issue(self, issue_id: int, title: str, state: str) -> None:
        table = self.query_one(DataTable)
        key = str(issue_id)
        try:
            table.update_cell(key, "num", f"#{issue_id}")
            table.update_cell(key, "title", title[:38])
            table.update_cell(key, "state", state)
        except CellDoesNotExist:
            table.add_row(f"#{issue_id}", title[:38], state, key=key)


class ActiveTaskPanel(Vertical):
    """Top-right: current task state, skill, todos."""

    DEFAULT_CSS = """
    ActiveTaskPanel {
        border: solid $panel;
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("Active Task", id="task-title")
        yield Static("", id="task-meta")
        yield ListView(id="task-todos")

    def update_task(
        self,
        issue_id: int,
        state: str,
        skill: str,
        retry: int,
        todos: list[str],
    ) -> None:
        self.query_one("#task-title", Static).update(f"Issue #{issue_id}")
        self.query_one("#task-meta", Static).update(
            f"State: {state}  Skill: {skill}  Retry: {retry}"
        )
        todo_list = self.query_one("#task-todos", ListView)
        todo_list.clear()
        for todo in todos:
            from textual.widgets import ListItem, Label
            todo_list.append(ListItem(Label(todo)))


class ApprovalPanel(Vertical):
    """Bottom-right: HITL gate — hidden until interrupt fires."""

    DEFAULT_CSS = """
    ApprovalPanel {
        border: solid $warning;
        height: 1fr;
        display: none;
    }
    ApprovalPanel.--visible {
        display: block;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("Awaiting Approval", id="approval-title")
        yield Static("", id="approval-description")
        yield Input(placeholder="[a]pprove / [r]eject / [i]nspect", id="approval-input")

    def show_operation(self, operation: str, details: dict) -> None:
        self.add_class("--visible")
        self.query_one("#approval-title", Static).update(f"HITL: {operation}")
        detail_str = "\n".join(f"  {k}: {v}" for k, v in details.items())
        self.query_one("#approval-description", Static).update(detail_str)

    def hide(self) -> None:
        self.remove_class("--visible")
        self.query_one("#approval-input", Input).value = ""
