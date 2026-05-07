"""Issue polling loop.

Sync `poll_once()` is the unit of work — orchestrator wraps it in an
async/await loop with `asyncio.sleep`. Keeps poller dependency-free of asyncio.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

from codepilot.github_io.client import GitHubClient
from codepilot.github_io.filters import DEFAULT_AI_LABEL, ComplexityFn, is_assignable
from codepilot.github_io.models import IssueRef
from codepilot.observability import Event, bind_task, get_logger
from codepilot.observability.audit import AuditLog


class IssuePoller:
    """Holds the in-progress set + selection rules. One per repo per process."""

    def __init__(
        self,
        client: GitHubClient,
        *,
        ai_label: str = DEFAULT_AI_LABEL,
        complexity_estimator: ComplexityFn | None = None,
        complexity_threshold: int | None = None,
        audit_log: AuditLog | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._client = client
        self._ai_label = ai_label
        self._complexity_estimator = complexity_estimator
        self._complexity_threshold = complexity_threshold
        self._audit = audit_log
        self._clock = clock or (lambda: 0.0)
        self._in_progress: set[int] = set()
        self._log = get_logger("github_io.poller")

    # ---- in-progress accounting ---------------------------------------

    def mark_in_progress(self, issue_number: int) -> None:
        self._in_progress.add(issue_number)

    def mark_done(self, issue_number: int) -> None:
        self._in_progress.discard(issue_number)

    @property
    def in_progress(self) -> frozenset[int]:
        return frozenset(self._in_progress)

    # ---- selection -----------------------------------------------------

    def _filter(self, issues: list[IssueRef]) -> list[IssueRef]:
        return [
            i for i in issues
            if is_assignable(
                i,
                in_progress_ids=self._in_progress,
                ai_label=self._ai_label,
                complexity_estimator=self._complexity_estimator,
                complexity_threshold=self._complexity_threshold,
            )
        ]

    # ---- one tick ------------------------------------------------------

    def poll_once(self) -> list[IssueRef]:
        """Fetch open issues, filter, return new pickups. Side-effect: emits audit + log."""
        raw = self._client.list_open_issues(exclude_ids=self._in_progress)
        new = self._filter(raw)

        for issue in new:
            with bind_task(issue.number, repo=issue.repo) as trace_id:
                self._log.info(
                    Event.ISSUE_PICKED_UP,
                    title=issue.title, labels=list(issue.labels),
                    reporter=issue.reporter,
                )
                if self._audit is not None:
                    self._audit.write(
                        Event.ISSUE_PICKED_UP,
                        {
                            "issue_id": issue.number,
                            "title": issue.title,
                            "labels": list(issue.labels),
                            "reporter": issue.reporter,
                        },
                        trace_id=trace_id,
                        issue_id=issue.number,
                        repo=issue.repo,
                    )
            self.mark_in_progress(issue.number)

        return new

    # ---- async loop ----------------------------------------------------

    async def stream(
        self,
        *,
        interval_sec: float,
        stop: asyncio.Event | None = None,
    ) -> AsyncIterator[IssueRef]:
        """Yield each new issue as it appears. Cancellable via `stop` event."""
        while True:
            if stop is not None and stop.is_set():
                return
            for issue in self.poll_once():
                yield issue
            try:
                if stop is None:
                    await asyncio.sleep(interval_sec)
                else:
                    await asyncio.wait_for(stop.wait(), timeout=interval_sec)
                    return
            except asyncio.TimeoutError:
                continue


def iter_pickups(poller: IssuePoller, ticks: int) -> Iterator[IssueRef]:
    """Sync helper for tests / scripts: drain N polling ticks."""
    for _ in range(ticks):
        yield from poller.poll_once()
