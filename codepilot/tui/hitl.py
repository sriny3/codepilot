"""HITL coordinator — blocks orchestrator thread until TUI user responds."""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from codepilot.tui.app import CodePilotApp


class HITLCoordinator:
    """Thread-safe approval gate between orchestrator and TUI.

    request_approval() blocks the calling (orchestrator) thread using
    threading.Event until resolve() is called from the TUI event loop.
    """

    def __init__(self, app: "CodePilotApp") -> None:
        self._app = app
        self._event = threading.Event()
        self._approved = False

    def request_approval(self, operation: str, details: dict[str, Any]) -> bool:
        """Block until TUI user approves or rejects. Returns True if approved."""
        self._event.clear()
        self._approved = False
        self._app.call_from_thread(self._app.show_approval_panel, operation, details)
        self._event.wait()
        return self._approved

    def resolve(self, *, approved: bool) -> None:
        """Called from TUI thread when user presses [a] or [r]."""
        self._approved = approved
        self._event.set()
