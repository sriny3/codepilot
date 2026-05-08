"""TUI app smoke tests using Textual's run_test() pilot."""
import pytest

from codepilot.tui.app import CodePilotApp


@pytest.mark.asyncio
async def test_app_starts_without_error() -> None:
    app = CodePilotApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.is_running


@pytest.mark.asyncio
async def test_data_table_present() -> None:
    from textual.widgets import DataTable

    app = CodePilotApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one(DataTable) is not None


@pytest.mark.asyncio
async def test_log_widget_present() -> None:
    from textual.widgets import Log

    app = CodePilotApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one(Log) is not None


@pytest.mark.asyncio
async def test_table_has_three_columns() -> None:
    from textual.widgets import DataTable

    app = CodePilotApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(DataTable)
        assert len(table.columns) == 3


@pytest.mark.asyncio
async def test_upsert_issue_adds_row() -> None:
    from textual.widgets import DataTable

    app = CodePilotApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.upsert_issue(42, "fix login", "EXPLORING")
        await pilot.pause()
        table = app.query_one(DataTable)
        assert table.row_count == 1


@pytest.mark.asyncio
async def test_upsert_issue_updates_existing_row() -> None:
    from textual.widgets import DataTable

    app = CodePilotApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.upsert_issue(1, "t", "EXPLORING")
        await pilot.pause()
        app.upsert_issue(1, "t", "DONE")
        await pilot.pause()
        table = app.query_one(DataTable)
        assert table.row_count == 1  # still one row, not two


@pytest.mark.asyncio
async def test_upsert_multiple_issues() -> None:
    from textual.widgets import DataTable

    app = CodePilotApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.upsert_issue(1, "a", "PENDING")
        app.upsert_issue(2, "b", "PENDING")
        app.upsert_issue(3, "c", "PENDING")
        await pilot.pause()
        table = app.query_one(DataTable)
        assert table.row_count == 3


@pytest.mark.asyncio
async def test_append_log_writes_line() -> None:
    from textual.widgets import Log

    app = CodePilotApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.append_log("issue.picked_up issue_id=42")
        await pilot.pause()
        log = app.query_one(Log)
        assert log.line_count >= 1


@pytest.mark.asyncio
async def test_quit_binding_exits() -> None:
    app = CodePilotApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("q")
        # app exits cleanly — no exception raised
