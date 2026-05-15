"""HITL coordinator — blocks orchestrator thread until TUI user responds."""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from codepilot.tui.app import CodePilotApp

# Default: auto-reject after 5 minutes of no response.
DEFAULT_TIMEOUT_SEC = 300


class HITLCoordinator:
    """Thread-safe approval gate between orchestrator and TUI.

    request_approval() blocks the calling (orchestrator) thread using
    threading.Event until resolve() is called from the TUI event loop,
    the timeout expires, or shutdown() is called (e.g. user presses q).

    Timeout and shutdown both auto-reject so the orchestrator thread
    unblocks and can reach its finally/cleanup path rather than hanging.
    """

    def __init__(self, app: "CodePilotApp", timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> None:
        self._app = app
        self._timeout_sec = timeout_sec
        self._event = threading.Event()
        self._approved = False
        self._shutdown = threading.Event()

    def request_approval(self, operation: str, details: dict[str, Any]) -> bool:
        """Block until TUI user approves/rejects, timeout, or shutdown.

        Returns True if approved, False on rejection, timeout, or shutdown.
        """
        self._event.clear()
        self._approved = False
        try:
            self._app.call_from_thread(self._app.show_approval_panel, operation, details)
        except RuntimeError:
            # App already shut down — auto-reject immediately.
            return False

        # Wait for whichever fires first: user response, timeout, or shutdown.
        resolved = self._event.wait(timeout=self._timeout_sec)
        if not resolved:
            # Timeout — log and auto-reject.
            try:
                self._app.call_from_thread(
                    self._app.append_log,
                    f"[HITL] Timeout ({self._timeout_sec:.0f}s) — auto-rejected: {operation}",
                )
                self._app.call_from_thread(self._app.hide_approval_panel)
            except RuntimeError:
                pass
            return False
        if self._shutdown.is_set():
            return False
        return self._approved

    def resolve(self, *, approved: bool) -> None:
        """Called from TUI thread when user presses [a] or [r]."""
        self._approved = approved
        self._event.set()

    def shutdown(self) -> None:
        """Unblock any waiting request_approval call on app exit."""
        self._shutdown.set()
        self._approved = False
        self._event.set()
