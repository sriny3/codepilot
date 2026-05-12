"""Tests for TUI widget color helpers."""
from codepilot.tui.widgets import _STATE_COLOR, _log_color


def test_state_color_covers_all_states():
    expected = {"TRIAGED", "EXPLORING", "IMPLEMENTING", "TESTING", "PR_OPENED", "DONE", "FAILED"}
    assert expected == set(_STATE_COLOR.keys())


def test_state_color_values_are_hex():
    for state, color in _STATE_COLOR.items():
        assert color.startswith("#"), f"{state} color {color!r} not a hex value"
        assert len(color) == 7, f"{state} color {color!r} not 6-digit hex"


def test_log_color_failed():
    assert _log_color("[coder] FAILED — tests did not pass") == "#e06c75"


def test_log_color_error():
    assert _log_color("[Orchestrator] ERROR #13: clone timed out") == "#e06c75"


def test_log_color_done():
    assert _log_color("[repo_explorer] done (26s) — 42 files") == "#5cb85c"


def test_log_color_success():
    assert _log_color("[pr_agent] success: PR #42 opened") == "#5cb85c"


def test_log_color_working():
    assert _log_color("[coder] working… (18s)") == "#e5c07b"


def test_log_color_default():
    assert _log_color("[Orchestrator] Picked up #13: Add chart feature") == "#b2c2d2"


def test_log_color_routing_arrow():
    assert _log_color("[→] task → repo_explorer") == "#b2c2d2"
