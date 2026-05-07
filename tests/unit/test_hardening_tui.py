"""Tests for Phase 13 TUI hardening: max_log_lines and thread-safe post_* wrappers."""
from __future__ import annotations

import threading

import pytest

from codepilot.tui.app import CodePilotApp
from codepilot.tui.models import TaskRow, TaskStatus


# ── max_log_lines ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_default_max_log_lines() -> None:
    from textual.widgets import Log

    app = CodePilotApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        log = app.query_one(Log)
        assert log.max_lines == 1000


@pytest.mark.asyncio
async def test_custom_max_log_lines() -> None:
    from textual.widgets import Log

    app = CodePilotApp(max_log_lines=50)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one(Log).max_lines == 50


@pytest.mark.asyncio
async def test_max_log_lines_limits_entries() -> None:
    from textual.widgets import Log

    app = CodePilotApp(max_log_lines=5)
    async with app.run_test() as pilot:
        await pilot.pause()
        for i in range(20):
            app.append_log(f"line {i}")
        await pilot.pause()
        assert app.query_one(Log).line_count <= 5


# ── post_* thread-safe wrappers ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_upsert_task_from_thread_adds_row() -> None:
    from textual.widgets import DataTable

    app = CodePilotApp()
    async with app.run_test() as pilot:
        await pilot.pause()

        def _worker() -> None:
            app.post_upsert_task(TaskRow(issue_id=42, title="fix bug"))

        t = threading.Thread(target=_worker)
        t.start()
        t.join(timeout=5.0)
        await pilot.pause()
        assert app.query_one(DataTable).row_count == 1


@pytest.mark.asyncio
async def test_post_append_log_from_thread_writes_line() -> None:
    from textual.widgets import Log

    app = CodePilotApp()
    async with app.run_test() as pilot:
        await pilot.pause()

        def _worker() -> None:
            app.post_append_log("tests.run passed=5 failed=0")

        t = threading.Thread(target=_worker)
        t.start()
        t.join(timeout=5.0)
        await pilot.pause()
        assert app.query_one(Log).line_count >= 1


@pytest.mark.asyncio
async def test_post_upsert_task_updates_existing_row() -> None:
    from textual.widgets import DataTable

    app = CodePilotApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.upsert_task(TaskRow(issue_id=1, title="t", status=TaskStatus.EXPLORING))
        await pilot.pause()

        def _worker() -> None:
            app.post_upsert_task(TaskRow(issue_id=1, title="t", status=TaskStatus.DONE))

        t = threading.Thread(target=_worker)
        t.start()
        t.join(timeout=5.0)
        await pilot.pause()
        assert app.query_one(DataTable).row_count == 1
