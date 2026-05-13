"""Unit tests for HITL retry-approval tool."""
from __future__ import annotations

from typing import Any

import pytest

from codepilot.agents.tools import github_tools
from codepilot.agents.tools.hitl_tools import request_retry_approval


class _FakeGate:
    """Stand-in for HITLCoordinator that records calls and returns a preset decision."""

    def __init__(self, approve: bool) -> None:
        self.approve = approve
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def request_approval(self, operation: str, details: dict[str, Any]) -> bool:
        self.calls.append((operation, details))
        return self.approve


@pytest.fixture(autouse=True)
def _restore_gate():
    """Ensure module-level _hitl_gate is reset around every test."""
    saved = github_tools._hitl_gate
    yield
    github_tools._hitl_gate = saved


def test_no_gate_auto_approves():
    github_tools._hitl_gate = None
    out = request_retry_approval.invoke({"failure_count": 3, "reason": "test failed"})
    assert out["approved"] is True
    assert out.get("note") == "no_gate_auto_approved"


def test_gate_approves():
    gate = _FakeGate(approve=True)
    github_tools._hitl_gate = gate
    out = request_retry_approval.invoke({"failure_count": 2, "reason": "flaky import"})
    assert out == {"approved": True}
    assert len(gate.calls) == 1
    op, details = gate.calls[0]
    assert op == "retry_after_failures"
    assert details["failures"] == 2
    assert "flaky import" in details["reason"]


def test_gate_rejects():
    gate = _FakeGate(approve=False)
    github_tools._hitl_gate = gate
    out = request_retry_approval.invoke({"failure_count": 4, "reason": "still failing"})
    assert out == {"approved": False, "reason": "rejected_by_human"}
    assert len(gate.calls) == 1


def test_reason_truncated_in_details():
    gate = _FakeGate(approve=True)
    github_tools._hitl_gate = gate
    long_reason = "x" * 500
    request_retry_approval.invoke({"failure_count": 2, "reason": long_reason})
    _, details = gate.calls[0]
    assert len(details["reason"]) <= 200
