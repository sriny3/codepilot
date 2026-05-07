"""Domain types for GitHub I/O. Decouple internal code from PyGithub object types."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class IssueRef:
    number: int
    title: str
    body: str
    labels: tuple[str, ...]
    assignees: tuple[str, ...]
    reporter: str | None
    repo: str
    state: str
    created_at: datetime | None
    url: str

    @classmethod
    def from_pygithub(cls, issue: Any, repo: str) -> "IssueRef":
        return cls(
            number=issue.number,
            title=issue.title or "",
            body=issue.body or "",
            labels=tuple(label.name for label in (issue.labels or [])),
            assignees=tuple(a.login for a in (issue.assignees or [])),
            reporter=(issue.user.login if issue.user else None),
            repo=repo,
            state=issue.state,
            created_at=issue.created_at,
            url=issue.html_url,
        )


@dataclass(frozen=True)
class BranchRef:
    name: str
    base_sha: str
    repo: str


@dataclass(frozen=True)
class CommitRef:
    sha: str
    files_changed: int
    branch: str
    repo: str


@dataclass(frozen=True)
class PRRef:
    number: int
    url: str
    base: str
    head: str
    title: str
    labels: tuple[str, ...] = field(default_factory=tuple)
    reviewer: str | None = None
