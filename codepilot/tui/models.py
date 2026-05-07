"""TUI data models — pure Python, no Textual dependency."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    TRIAGED = "TRIAGED"
    EXPLORING = "EXPLORING"
    IMPLEMENTING = "IMPLEMENTING"
    TESTING = "TESTING"
    PR_OPENED = "PR_OPENED"
    DONE = "DONE"
    FAILED = "FAILED"


_STATE_TO_STATUS: dict[str, TaskStatus] = {s.value: s for s in TaskStatus}


@dataclass
class TaskRow:
    """One row in the TUI task table."""

    issue_id: int
    title: str
    status: TaskStatus = TaskStatus.PENDING
    retry_count: int = 0
    pr_url: str = ""
    skill: str = ""
    todos: list[str] = field(default_factory=list)

    _TITLE_MAX = 38

    def to_table_row(self) -> tuple[str, str, str, str, str]:
        title = (
            self.title[: self._TITLE_MAX - 1] + "…"
            if len(self.title) > self._TITLE_MAX
            else self.title
        )
        return (
            f"#{self.issue_id}",
            title,
            self.status.value,
            str(self.retry_count),
            self.pr_url,
        )

    @classmethod
    def from_working_memory(
        cls,
        issue_id: int,
        title: str,
        *,
        state: str,
        retry_count: int = 0,
        pr_url: str = "",
        skill: str = "",
        todos: list[str] | None = None,
    ) -> "TaskRow":
        status = _STATE_TO_STATUS.get(state, TaskStatus.PENDING)
        return cls(
            issue_id=issue_id,
            title=title,
            status=status,
            retry_count=retry_count,
            pr_url=pr_url,
            skill=skill,
            todos=todos or [],
        )
