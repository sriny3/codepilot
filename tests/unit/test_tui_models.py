"""Tests for TUI data models — no Textual dependency."""
import pytest

from codepilot.tui.models import TaskRow, TaskStatus


# ── TaskStatus ────────────────────────────────────────────────────────────────


class TestTaskStatus:
    def test_values_match_task_state_names(self) -> None:
        from codepilot.memory.state import TaskState

        for ts in TaskState:
            assert ts.value in {s.value for s in TaskStatus}

    def test_is_string_enum(self) -> None:
        assert isinstance(TaskStatus.DONE, str)

    def test_pending_exists(self) -> None:
        assert TaskStatus.PENDING.value == "PENDING"

    def test_failed_exists(self) -> None:
        assert TaskStatus.FAILED.value == "FAILED"


# ── TaskRow ───────────────────────────────────────────────────────────────────


class TestTaskRow:
    def test_default_status_is_pending(self) -> None:
        row = TaskRow(issue_id=1, title="x")
        assert row.status == TaskStatus.PENDING

    def test_default_retry_zero(self) -> None:
        row = TaskRow(issue_id=1, title="x")
        assert row.retry_count == 0

    def test_default_pr_url_empty(self) -> None:
        row = TaskRow(issue_id=1, title="x")
        assert row.pr_url == ""

    def test_to_table_row_length(self) -> None:
        row = TaskRow(issue_id=7, title="fix bug", status=TaskStatus.TESTING)
        cells = row.to_table_row()
        assert len(cells) == 5

    def test_to_table_row_issue_id(self) -> None:
        row = TaskRow(issue_id=42, title="x")
        assert row.to_table_row()[0] == "#42"

    def test_to_table_row_status(self) -> None:
        row = TaskRow(issue_id=1, title="x", status=TaskStatus.DONE)
        assert row.to_table_row()[2] == "DONE"

    def test_to_table_row_retry_count(self) -> None:
        row = TaskRow(issue_id=1, title="x", retry_count=3)
        assert row.to_table_row()[3] == "3"

    def test_to_table_row_pr_url(self) -> None:
        row = TaskRow(issue_id=1, title="x", pr_url="https://github.com/a/b/pull/5")
        assert row.to_table_row()[4] == "https://github.com/a/b/pull/5"

    def test_long_title_truncated(self) -> None:
        long = "a" * 60
        row = TaskRow(issue_id=1, title=long)
        cell = row.to_table_row()[1]
        assert len(cell) <= TaskRow._TITLE_MAX
        assert cell.endswith("…")

    def test_short_title_not_truncated(self) -> None:
        row = TaskRow(issue_id=1, title="short")
        assert row.to_table_row()[1] == "short"

    def test_all_cells_are_strings(self) -> None:
        row = TaskRow(issue_id=5, title="t", status=TaskStatus.IMPLEMENTING, retry_count=2)
        for cell in row.to_table_row():
            assert isinstance(cell, str)


# ── TaskRow.from_working_memory ───────────────────────────────────────────────


class TestTaskRowFromWorkingMemory:
    def test_maps_known_state(self) -> None:
        row = TaskRow.from_working_memory(1, "t", state="TESTING")
        assert row.status == TaskStatus.TESTING

    def test_unknown_state_falls_back_to_pending(self) -> None:
        row = TaskRow.from_working_memory(1, "t", state="UNKNOWN")
        assert row.status == TaskStatus.PENDING

    def test_retry_count_forwarded(self) -> None:
        row = TaskRow.from_working_memory(1, "t", state="IMPLEMENTING", retry_count=2)
        assert row.retry_count == 2

    def test_pr_url_forwarded(self) -> None:
        row = TaskRow.from_working_memory(
            1, "t", state="PR_OPENED", pr_url="https://github.com/x/pull/1"
        )
        assert row.pr_url == "https://github.com/x/pull/1"

    def test_issue_id_and_title_set(self) -> None:
        row = TaskRow.from_working_memory(99, "add feature", state="DONE")
        assert row.issue_id == 99
        assert row.title == "add feature"
