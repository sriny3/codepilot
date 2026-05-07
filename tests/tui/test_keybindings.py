"""Tests for TUI keybindings."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_q_quits_app() -> None:
    from codepilot.tui.app import CodePilotApp

    app = CodePilotApp()
    async with app.run_test() as pilot:
        await pilot.press("q")
        assert app._exit is True or not app.is_running


@pytest.mark.asyncio
async def test_l_toggles_log_visibility() -> None:
    from codepilot.tui.app import CodePilotApp
    from textual.widgets import Log

    app = CodePilotApp()
    async with app.run_test() as pilot:
        log = app.query_one(Log)
        initial_display = log.display
        await pilot.press("l")
        await pilot.pause()
        assert log.display != initial_display
