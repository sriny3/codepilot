"""TUI integration tests — verify the dashboard reflects pipeline state changes."""
from __future__ import annotations

import pytest

from codepilot.tui.app import CodePilotApp
from codepilot.tui.models import TaskRow, TaskStatus


@pytest.mark.asyncio
async def test_initial_table_is_empty() -> None:
    from textual.widgets import DataTable

    app = CodePilotApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one(DataTable).row_count == 0


@pytest.mark.asyncio
async def test_new_issue_appears_in_table() -> None:
    from textual.widgets import DataTable

    app = CodePilotApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.upsert_task(TaskRow(issue_id=42, title="fix login", status=TaskStatus.EXPLORING))
        await pilot.pause()
        assert app.query_one(DataTable).row_count == 1


@pytest.mark.asyncio
async def test_status_updates_do_not_add_duplicate_rows() -> None:
    from textual.widgets import DataTable

    app = CodePilotApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        for status in (
            TaskStatus.EXPLORING,
            TaskStatus.IMPLEMENTING,
            TaskStatus.TESTING,
            TaskStatus.PR_OPENED,
            TaskStatus.DONE,
        ):
            app.upsert_task(TaskRow(issue_id=7, title="t", status=status))
            await pilot.pause()
        assert app.query_one(DataTable).row_count == 1


@pytest.mark.asyncio
async def test_multiple_issues_tracked_simultaneously() -> None:
    from textual.widgets import DataTable

    app = CodePilotApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.upsert_task(TaskRow(issue_id=1, title="issue one", status=TaskStatus.IMPLEMENTING))
        app.upsert_task(TaskRow(issue_id=2, title="issue two", status=TaskStatus.TESTING))
        app.upsert_task(TaskRow(issue_id=3, title="issue three", status=TaskStatus.DONE))
        await pilot.pause()
        assert app.query_one(DataTable).row_count == 3


@pytest.mark.asyncio
async def test_log_receives_pipeline_events() -> None:
    from textual.widgets import Log

    app = CodePilotApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.append_log("repo_map.built entries=143")
        app.append_log("edit.applied path=src/auth.py")
        app.append_log("tests.run passed=5 failed=0")
        app.append_log("pr.opened pr_number=17 url=https://github.com/a/b/pull/17")
        await pilot.pause()
        assert app.query_one(Log).line_count >= 4


@pytest.mark.asyncio
async def test_failed_task_tracked() -> None:
    from textual.widgets import DataTable

    app = CodePilotApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.upsert_task(TaskRow(issue_id=99, title="broken task", status=TaskStatus.FAILED))
        await pilot.pause()
        assert app.query_one(DataTable).row_count == 1


@pytest.mark.asyncio
async def test_pr_url_visible_after_completion() -> None:
    from textual.widgets import DataTable

    app = CodePilotApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.upsert_task(
            TaskRow(
                issue_id=5,
                title="add feature",
                status=TaskStatus.DONE,
                pr_url="https://github.com/acme/x/pull/3",
            )
        )
        await pilot.pause()
        assert app.query_one(DataTable).row_count == 1


@pytest.mark.asyncio
async def test_retry_count_updates_in_table() -> None:
    from textual.widgets import DataTable

    app = CodePilotApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.upsert_task(TaskRow(issue_id=10, title="flaky fix", retry_count=0))
        await pilot.pause()
        app.upsert_task(TaskRow(issue_id=10, title="flaky fix", retry_count=2))
        await pilot.pause()
        assert app.query_one(DataTable).row_count == 1
