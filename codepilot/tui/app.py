"""CodePilot TUI — live task dashboard."""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, Log

from codepilot.tui.models import TaskRow

_COL_KEYS = ("issue", "title", "state", "retry", "pr")
_COL_LABELS = ("Issue", "Title", "State", "Retry", "PR")


class CodePilotApp(App[None]):
    """Terminal dashboard: task table on top, event log below."""

    TITLE = "CodePilot"
    SUB_TITLE = "autonomous coding agent"

    CSS = """
    Vertical {
        height: 1fr;
    }
    DataTable {
        height: 1fr;
        border-bottom: solid $panel-darken-1;
    }
    Log {
        height: 1fr;
    }
    """

    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, *, max_log_lines: int = 1000) -> None:
        super().__init__()
        self._task_keys: set[str] = set()
        self._max_log_lines = max_log_lines

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield DataTable()
            yield Log(max_lines=self._max_log_lines)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        for key, label in zip(_COL_KEYS, _COL_LABELS):
            table.add_column(label, key=key)

    def upsert_task(self, row: TaskRow) -> None:
        """Add or update a task row. Safe to call from any thread via call_from_thread."""
        table = self.query_one(DataTable)
        key = str(row.issue_id)
        cells = row.to_table_row()
        if key in self._task_keys:
            for col_key, value in zip(_COL_KEYS, cells):
                table.update_cell(key, col_key, value)
        else:
            table.add_row(*cells, key=key)
            self._task_keys.add(key)

    def append_log(self, message: str) -> None:
        """Append a line to the event log. Safe to call from any thread via call_from_thread."""
        self.query_one(Log).write_line(message)

    def post_upsert_task(self, row: TaskRow) -> None:
        """Thread-safe upsert: schedules upsert_task on the Textual event loop."""
        self.call_from_thread(self.upsert_task, row)

    def post_append_log(self, message: str) -> None:
        """Thread-safe log: schedules append_log on the Textual event loop."""
        self.call_from_thread(self.append_log, message)
