"""Episodic memory: per-session task summaries persisted via LangGraph BaseStore.

Used by the orchestrator at startup to read the last 3 session summaries —
prevents retrying recently-failed issues without paying for a full re-run.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from pydantic import BaseModel, Field


SESSION_NAMESPACE = ("codepilot", "sessions")
TASK_NAMESPACE = ("codepilot", "tasks")


class TaskOutcome(BaseModel):
    issue_id: int
    repo: str
    task_type: str | None = None
    files_modified: list[str] = Field(default_factory=list)
    outcome: str  # "DONE" | "FAILED"
    duration_ms: int = 0
    pr_number: int | None = None
    note: str | None = None


class SessionSummary(BaseModel):
    session_id: str
    started_at: datetime
    ended_at: datetime
    tasks: list[TaskOutcome] = Field(default_factory=list)

    @property
    def attempted_issue_ids(self) -> list[int]:
        return [t.issue_id for t in self.tasks]

    @property
    def failed_issue_ids(self) -> list[int]:
        return [t.issue_id for t in self.tasks if t.outcome != "DONE"]


class EpisodicStore:
    """Thin facade over `BaseStore`.

    Production wires `InMemoryStore` (single-process) or a Postgres-backed
    LangGraph store. Tests pass `InMemoryStore` directly.
    """

    def __init__(self, store: BaseStore | None = None) -> None:
        self._store = store or InMemoryStore()

    @property
    def store(self) -> BaseStore:
        return self._store

    # ---- task records (one per attempted issue) -----------------------

    def record_task(self, *, session_id: str, outcome: TaskOutcome) -> str:
        key = f"{session_id}:{outcome.issue_id}"
        self._store.put(TASK_NAMESPACE, key, outcome.model_dump(mode="json"))
        return key

    def task_records(self, session_id: str) -> list[TaskOutcome]:
        items = self._store.search(TASK_NAMESPACE, filter={})
        out: list[TaskOutcome] = []
        for item in items:
            if not item.key.startswith(f"{session_id}:"):
                continue
            out.append(TaskOutcome.model_validate(item.value))
        return out

    # ---- session summaries (closing record) ---------------------------

    def write_session(self, summary: SessionSummary) -> None:
        self._store.put(
            SESSION_NAMESPACE,
            summary.session_id,
            summary.model_dump(mode="json"),
        )

    def get_session(self, session_id: str) -> SessionSummary | None:
        item = self._store.get(SESSION_NAMESPACE, session_id)
        if item is None:
            return None
        return SessionSummary.model_validate(item.value)

    def recent_sessions(self, n: int = 3) -> list[SessionSummary]:
        items = self._store.search(SESSION_NAMESPACE, filter={})
        sessions = [SessionSummary.model_validate(i.value) for i in items]
        sessions.sort(key=lambda s: s.ended_at, reverse=True)
        return sessions[:n]

    def recently_failed_issue_ids(self, n: int = 3) -> set[int]:
        ids: set[int] = set()
        for s in self.recent_sessions(n=n):
            ids.update(s.failed_issue_ids)
        return ids


def new_session_id() -> str:
    return uuid.uuid4().hex


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
