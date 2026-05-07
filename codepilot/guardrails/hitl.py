"""Human-in-the-loop gate. Async approval workflow with pluggable backends."""
from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

from codepilot.observability import get_logger

if TYPE_CHECKING:
    from codepilot.observability.audit import AuditLog

_log = get_logger("guardrails.hitl")


# ── Exception ─────────────────────────────────────────────────────────────────


class NeedsApproval(Exception):
    """Raised by non-interactive HITL backends when approval cannot be obtained."""

    def __init__(self, operation: str, context: dict[str, Any]) -> None:
        super().__init__(f"human approval required for: {operation!r}")
        self.operation = operation
        self.context = context


# ── Condition table ────────────────────────────────────────────────────────────


class HitlCondition(ABC):
    """Abstract base for a single HITL trigger condition."""

    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description

    @abstractmethod
    def should_trigger(self, *, operation: str, context: dict[str, Any]) -> bool:
        """Return True when this condition requires human approval."""


class PrToProtectedBranch(HitlCondition):
    """Fires when a PR targets a protected branch (main, master, release, …)."""

    _DEFAULT_PROTECTED: frozenset[str] = frozenset({"main", "master", "release", "develop"})

    def __init__(self, protected: frozenset[str] | None = None) -> None:
        super().__init__("pr_to_protected_branch", "PR targets a protected branch")
        self._protected = protected if protected is not None else self._DEFAULT_PROTECTED

    def should_trigger(self, *, operation: str, context: dict[str, Any]) -> bool:
        return operation == "open_pr" and context.get("base_branch") in self._protected


class LargeCommit(HitlCondition):
    """Fires when a commit touches more than `threshold` files."""

    def __init__(self, threshold: int = 5) -> None:
        super().__init__("large_commit", f"commit touches more than {threshold} files")
        self._threshold = threshold

    def should_trigger(self, *, operation: str, context: dict[str, Any]) -> bool:
        return (
            operation in ("create_commit", "commit")
            and int(context.get("files_changed", 0)) > self._threshold
        )


class RemotePush(HitlCondition):
    """Fires on any git push to a remote."""

    def __init__(self) -> None:
        super().__init__("remote_push", "git push to remote")

    def should_trigger(self, *, operation: str, context: dict[str, Any]) -> bool:
        return operation in ("git_push", "push")


class MaxRetriesReached(HitlCondition):
    """Fires when the task's retry counter has hit `max_retries`."""

    def __init__(self, max_retries: int = 2) -> None:
        super().__init__(
            "max_retries_reached",
            f"task retry count reached {max_retries}",
        )
        self._max = max_retries

    def should_trigger(self, *, operation: str, context: dict[str, Any]) -> bool:
        return int(context.get("retry_count", 0)) >= self._max


DEFAULT_CONDITIONS: tuple[HitlCondition, ...] = (
    PrToProtectedBranch(),
    LargeCommit(threshold=5),
    RemotePush(),
    MaxRetriesReached(max_retries=2),
)


def check_hitl_conditions(
    *,
    operation: str,
    context: dict[str, Any],
    conditions: tuple[HitlCondition, ...] | None = None,
) -> HitlCondition | None:
    """Return the first condition that fires, or None if none trigger."""
    for cond in (conditions if conditions is not None else DEFAULT_CONDITIONS):
        if cond.should_trigger(operation=operation, context=context):
            return cond
    return None


# ── Gate implementations ───────────────────────────────────────────────────────


class ConsoleHitlGate:
    """Prompts operator on stdout/stdin. Phase 11 replaces with TUI widget."""

    def __init__(
        self,
        conditions: tuple[HitlCondition, ...] | None = None,
        audit: "AuditLog | None" = None,
    ) -> None:
        self._conditions = conditions if conditions is not None else DEFAULT_CONDITIONS
        self._audit = audit

    def needs_approval(
        self, *, operation: str, context: dict[str, Any]
    ) -> HitlCondition | None:
        return check_hitl_conditions(
            operation=operation, context=context, conditions=self._conditions
        )

    async def request_approval(
        self,
        *,
        operation: str,
        context: dict[str, Any],
        agent: str = "orchestrator",
    ) -> bool:
        from codepilot.observability.events import Event

        summary = f"operation={operation!r} " + " ".join(
            f"{k}={v}" for k, v in list(context.items())[:5]
        )
        _log.warning("hitl.requested", operation=operation, agent=agent)

        if self._audit is not None:
            self._audit.write(
                Event.HITL_REQUESTED,
                {"operation": operation, "context_summary": summary[:200]},
                actor=agent,
            )

        started_at = time.monotonic()

        def _prompt() -> str:
            print(f"\n[HITL] Approval required: {operation!r}")
            for k, v in context.items():
                print(f"  {k}: {v}")
            return input("Approve? [y/N]: ").strip().lower()

        answer = await asyncio.get_event_loop().run_in_executor(None, _prompt)
        approved = answer in ("y", "yes")
        latency_ms = int((time.monotonic() - started_at) * 1000)
        approver = str(context.get("approver_login", "cli_user"))

        _log.info(
            "hitl.decision",
            decision="approve" if approved else "reject",
            operation=operation,
            approver=approver,
            latency_ms=latency_ms,
        )

        if self._audit is not None:
            self._audit.write(
                Event.HITL_DECISION,
                {
                    "decision": "approve" if approved else "reject",
                    "approver_login": approver,
                    "reason": None,
                    "latency_ms": latency_ms,
                },
                actor=agent,
            )

        return approved


class AutoApproveGate:
    """Always approves without prompting. Use in tests and non-interactive CI."""

    def __init__(
        self, conditions: tuple[HitlCondition, ...] | None = None
    ) -> None:
        self._conditions = conditions if conditions is not None else DEFAULT_CONDITIONS

    def needs_approval(
        self, *, operation: str, context: dict[str, Any]
    ) -> HitlCondition | None:
        return check_hitl_conditions(
            operation=operation, context=context, conditions=self._conditions
        )

    async def request_approval(
        self,
        *,
        operation: str,
        context: dict[str, Any],
        agent: str = "orchestrator",
    ) -> bool:
        _log.debug("hitl.auto_approve", operation=operation, agent=agent)
        return True


class AutoRejectGate:
    """Always rejects without prompting. Use to test rejection-handling paths."""

    def __init__(
        self, conditions: tuple[HitlCondition, ...] | None = None
    ) -> None:
        self._conditions = conditions if conditions is not None else DEFAULT_CONDITIONS

    def needs_approval(
        self, *, operation: str, context: dict[str, Any]
    ) -> HitlCondition | None:
        return check_hitl_conditions(
            operation=operation, context=context, conditions=self._conditions
        )

    async def request_approval(
        self,
        *,
        operation: str,
        context: dict[str, Any],
        agent: str = "orchestrator",
    ) -> bool:
        _log.debug("hitl.auto_reject", operation=operation, agent=agent)
        return False


class RaisingHitlGate:
    """Raises NeedsApproval. Use in non-interactive environments where blocking is wrong."""

    def __init__(
        self, conditions: tuple[HitlCondition, ...] | None = None
    ) -> None:
        self._conditions = conditions if conditions is not None else DEFAULT_CONDITIONS

    def needs_approval(
        self, *, operation: str, context: dict[str, Any]
    ) -> HitlCondition | None:
        return check_hitl_conditions(
            operation=operation, context=context, conditions=self._conditions
        )

    async def request_approval(
        self,
        *,
        operation: str,
        context: dict[str, Any],
        agent: str = "orchestrator",
    ) -> bool:
        raise NeedsApproval(operation, context)
