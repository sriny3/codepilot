"""Tests for CodePilotApp 4-panel layout."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_all_four_panels_mount() -> None:
    from codepilot.tui.app import CodePilotApp
    from codepilot.tui.widgets import ActiveTaskPanel, ApprovalPanel, IssuesPanel

    app = CodePilotApp()
    async with app.run_test() as pilot:
        assert app.query_one(IssuesPanel) is not None
        assert app.query_one(ActiveTaskPanel) is not None
        assert app.query_one(ApprovalPanel) is not None
        log_widget = app.query("RichLog")
        assert len(log_widget) > 0


@pytest.mark.asyncio
async def test_approval_panel_hidden_by_default() -> None:
    from codepilot.tui.app import CodePilotApp
    from codepilot.tui.widgets import ApprovalPanel

    app = CodePilotApp()
    async with app.run_test() as pilot:
        panel = app.query_one(ApprovalPanel)
        assert "--visible" not in panel.classes


@pytest.mark.asyncio
async def test_show_approval_panel_makes_visible() -> None:
    from codepilot.tui.app import CodePilotApp
    from codepilot.tui.widgets import ApprovalPanel

    app = CodePilotApp()
    async with app.run_test() as pilot:
        app.show_approval_panel("open_pr", {"title": "fix auth"})
        await pilot.pause()
        panel = app.query_one(ApprovalPanel)
        assert "--visible" in panel.classes
