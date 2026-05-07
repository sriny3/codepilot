"""Tests for HITLCoordinator threading behavior."""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock


class TestHITLCoordinator:
    def test_approve_returns_true(self) -> None:
        from codepilot.tui.hitl import HITLCoordinator

        app = MagicMock()
        coordinator = HITLCoordinator(app)

        def approve_after_delay() -> None:
            time.sleep(0.05)
            coordinator.resolve(approved=True)

        thread = threading.Thread(target=approve_after_delay)
        thread.start()
        result = coordinator.request_approval("open_pr", {"pr_number": 42})
        thread.join()

        assert result is True

    def test_reject_returns_false(self) -> None:
        from codepilot.tui.hitl import HITLCoordinator

        app = MagicMock()
        coordinator = HITLCoordinator(app)

        def reject_after_delay() -> None:
            time.sleep(0.05)
            coordinator.resolve(approved=False)

        thread = threading.Thread(target=reject_after_delay)
        thread.start()
        result = coordinator.request_approval("commit_files", {"files": ["src/main.py"]})
        thread.join()

        assert result is False

    def test_app_show_approval_called(self) -> None:
        from codepilot.tui.hitl import HITLCoordinator

        app = MagicMock()
        coordinator = HITLCoordinator(app)

        def resolve() -> None:
            time.sleep(0.05)
            coordinator.resolve(approved=True)

        thread = threading.Thread(target=resolve)
        thread.start()
        coordinator.request_approval("open_pr", {"title": "fix auth"})
        thread.join()

        app.call_from_thread.assert_called_once()
