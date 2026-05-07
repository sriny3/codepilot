"""Working memory: per-task state machine + the transient bag of work-in-progress data.

Lives in process. Cleared on DONE or FAILED. Passed explicitly to subagents at
spawn time rather than relying on conversation history (DeepAgents context-engineering rule).
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TaskState(str, Enum):
    TRIAGED = "TRIAGED"
    EXPLORING = "EXPLORING"
    IMPLEMENTING = "IMPLEMENTING"
    TESTING = "TESTING"
    PR_OPENED = "PR_OPENED"
    DONE = "DONE"
    FAILED = "FAILED"


# Allowed forward transitions. Reverse + jumps must go through FAILED.
TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.TRIAGED:      frozenset({TaskState.EXPLORING, TaskState.FAILED}),
    TaskState.EXPLORING:    frozenset({TaskState.IMPLEMENTING, TaskState.FAILED}),
    TaskState.IMPLEMENTING: frozenset({TaskState.TESTING, TaskState.IMPLEMENTING,
                                       TaskState.FAILED}),
    TaskState.TESTING:      frozenset({TaskState.PR_OPENED, TaskState.IMPLEMENTING,
                                       TaskState.FAILED}),
    TaskState.PR_OPENED:    frozenset({TaskState.DONE, TaskState.FAILED}),
    TaskState.DONE:         frozenset(),  # terminal
    TaskState.FAILED:       frozenset(),  # terminal
}

TERMINAL_STATES: frozenset[TaskState] = frozenset({TaskState.DONE, TaskState.FAILED})


class InvalidTransition(ValueError):
    """Raised when a state machine edge is not in TRANSITIONS."""


class TestRunSummary(BaseModel):
    __test__ = False  # tell pytest this isn't a test class

    passed: int = 0
    failed: int = 0
    framework: str | None = None
    failures: list[dict[str, Any]] = Field(default_factory=list)


class WorkingMemory(BaseModel):
    """Mutable bag of facts for one task. Pydantic model for free validation + dump."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    issue_id: int
    repo: str
    trace_id: str
    task_type: str | None = None
    state: TaskState = TaskState.TRIAGED
    repo_map_path: str | None = None
    relevant_files: list[str] = Field(default_factory=list)
    proposed_diff: str | None = None
    test_results: TestRunSummary | None = None
    retry_count: int = 0
    notes: list[str] = Field(default_factory=list)

    @field_validator("retry_count")
    @classmethod
    def _retry_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("retry_count must be >= 0")
        return v

    # ---- transitions ---------------------------------------------------

    def transition(self, target: TaskState) -> "WorkingMemory":
        """Move to `target`. Raises `InvalidTransition` on illegal edge."""
        if self.is_terminal():
            raise InvalidTransition(
                f"task already terminal in {self.state}; cannot move to {target}"
            )
        allowed = TRANSITIONS[self.state]
        if target not in allowed:
            raise InvalidTransition(
                f"illegal transition {self.state} → {target}; "
                f"allowed: {sorted(s.value for s in allowed)}"
            )
        self.state = target
        return self

    def fail(self, reason: str) -> "WorkingMemory":
        if self.is_terminal():
            return self
        self.notes.append(f"FAILED: {reason}")
        self.state = TaskState.FAILED
        return self

    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def bump_retry(self) -> int:
        self.retry_count += 1
        return self.retry_count

    # ---- subagent handoff ---------------------------------------------

    def for_subagent(self) -> dict[str, Any]:
        """Snapshot to pass to a subagent. File paths only — no contents."""
        return {
            "issue_id": self.issue_id,
            "repo": self.repo,
            "trace_id": self.trace_id,
            "task_type": self.task_type,
            "state": self.state.value,
            "repo_map_path": self.repo_map_path,
            "relevant_files": list(self.relevant_files),
            "retry_count": self.retry_count,
        }


class WorkingMemoryRegistry:
    """One in-process map of issue_id → WorkingMemory. Cleared on terminal."""

    def __init__(self) -> None:
        self._mems: dict[int, WorkingMemory] = {}

    def open(self, *, issue_id: int, repo: str, trace_id: str,
             task_type: str | None = None) -> WorkingMemory:
        if issue_id in self._mems:
            raise ValueError(f"working memory already open for issue {issue_id}")
        wm = WorkingMemory(
            issue_id=issue_id, repo=repo, trace_id=trace_id, task_type=task_type,
        )
        self._mems[issue_id] = wm
        return wm

    def get(self, issue_id: int) -> WorkingMemory:
        return self._mems[issue_id]

    def close(self, issue_id: int) -> None:
        wm = self._mems.get(issue_id)
        if wm is None:
            return
        if not wm.is_terminal():
            raise InvalidTransition(
                f"refusing to close working memory in non-terminal state {wm.state}"
            )
        del self._mems[issue_id]

    def __contains__(self, issue_id: int) -> bool:
        return issue_id in self._mems

    def __len__(self) -> int:
        return len(self._mems)
