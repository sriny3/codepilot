"""HITL @tool wrappers — let agents explicitly pause for human approval."""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from codepilot.agents.tools import github_tools as _gh


@tool
def request_retry_approval(failure_count: int, reason: str) -> dict:
    """Pause and ask the human to approve another retry attempt after repeated failures.

    Call this BEFORE any retry attempt beyond the second consecutive failure
    (i.e. before attempt 3, 4, ...). Spec rule: "Retry after 2 failed test runs"
    requires explicit human approval to prevent infinite loops.

    Args:
        failure_count: Number of consecutive failures so far (>= 2 to gate).
        reason: Short description of what failed and why a retry is being considered.

    Returns:
        {"approved": True}  — proceed with the retry.
        {"approved": False, "reason": "rejected_by_human"} — abort, set state to FAILED.
    """
    _gh._trace("request_retry_approval", failure_count=failure_count, reason=reason[:80])
    gate = _gh._hitl_gate
    if gate is None:
        # Fallback: no gate registered means we are not in TUI mode (e.g. tests).
        # Auto-approve so non-TUI callers do not deadlock.
        result: dict[str, Any] = {"approved": True, "note": "no_gate_auto_approved"}
        _gh._trace_result("request_retry_approval", result)
        return result
    approved = gate.request_approval(
        "retry_after_failures",
        {
            "value": f"Approve retry after {failure_count} failed attempts?",
            "failures": failure_count,
            "reason": reason[:200],
        },
    )
    result = {"approved": True} if approved else {"approved": False, "reason": "rejected_by_human"}
    _gh._trace_result("request_retry_approval", result)
    return result
