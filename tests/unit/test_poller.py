import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from codepilot.github_io.client import GitHubClient
from codepilot.github_io.poller import IssuePoller, iter_pickups
from codepilot.observability import logger as log_mod
from codepilot.observability.audit import AuditLog
from codepilot.observability.events import Event
from tests.unit._gh_fakes import FakeGitHub, FakeIssue, FakeLabel, FakeRepo, FakeUser


@pytest.fixture(autouse=True)
def _reset_logging(tmp_path: Path) -> None:
    log_mod.reset_for_tests()
    log_mod.configure(level="INFO", log_dir=tmp_path, log_format="json")
    yield
    log_mod.reset_for_tests()


def _seed_repo() -> FakeRepo:
    r = FakeRepo()
    r.issues = [
        FakeIssue(
            number=1, title="Bug A", labels=[FakeLabel("ai-assignable")],
            user=FakeUser("alice"),
            created_at=datetime(2026, 5, 4, tzinfo=timezone.utc),
        ),
        FakeIssue(
            number=2, title="Feature B", assignees=[FakeUser("dave")],
            user=FakeUser("alice"),
        ),
        FakeIssue(
            number=3, title="Docs C", user=FakeUser("alice"),
        ),
    ]
    return r


def _make_client() -> tuple[FakeRepo, GitHubClient]:
    r = _seed_repo()
    return r, GitHubClient(FakeGitHub(repo=r), "acme/x")


class TestPollOnceFiltering:
    def test_picks_only_assignable(self) -> None:
        _, client = _make_client()
        p = IssuePoller(client, complexity_threshold=10,
                        complexity_estimator=lambda i: 5)
        picked = p.poll_once()
        # Issue 1 (label) and 3 (unassigned, complexity ok). Issue 2 assigned, no label → skip.
        assert {i.number for i in picked} == {1, 3}

    def test_skips_already_in_progress(self) -> None:
        _, client = _make_client()
        p = IssuePoller(client, complexity_threshold=10,
                        complexity_estimator=lambda i: 5)
        p.mark_in_progress(1)
        picked = p.poll_once()
        assert {i.number for i in picked} == {3}


class TestInProgressLifecycle:
    def test_pickup_marks_in_progress(self) -> None:
        _, client = _make_client()
        p = IssuePoller(client, complexity_threshold=10,
                        complexity_estimator=lambda i: 5)
        p.poll_once()
        assert p.in_progress == frozenset({1, 3})

    def test_repeat_poll_returns_nothing_until_done(self) -> None:
        _, client = _make_client()
        p = IssuePoller(client, complexity_threshold=10,
                        complexity_estimator=lambda i: 5)
        first = p.poll_once()
        second = p.poll_once()
        assert first
        assert second == []
        p.mark_done(1)
        third = p.poll_once()
        assert {i.number for i in third} == {1}


class TestAuditEmission:
    def test_pickup_writes_audit_with_trace(self, tmp_path: Path) -> None:
        _, client = _make_client()
        audit = AuditLog(tmp_path)
        p = IssuePoller(client, complexity_threshold=10,
                        complexity_estimator=lambda i: 5,
                        audit_log=audit)
        p.poll_once()
        audit.close()

        files = list(tmp_path.glob("audit-*.jsonl"))
        assert len(files) == 1
        rows = [
            json.loads(l) for l in files[0].read_text(encoding="utf-8").splitlines() if l.strip()
        ]
        events = [r for r in rows if r["event"] == Event.ISSUE_PICKED_UP]
        assert {r["details"]["issue_id"] for r in events} == {1, 3}
        # Each pickup gets its own trace_id.
        traces = {r["trace_id"] for r in events}
        assert len(traces) == 2
        for tid in traces:
            assert tid

    def test_no_audit_no_emission(self) -> None:
        _, client = _make_client()
        p = IssuePoller(client, complexity_threshold=10,
                        complexity_estimator=lambda i: 5,
                        audit_log=None)
        # Just confirms it doesn't crash without an audit log wired.
        assert p.poll_once()


class TestIterHelper:
    def test_iter_pickups_drains_n_ticks(self) -> None:
        _, client = _make_client()
        p = IssuePoller(client, complexity_threshold=10,
                        complexity_estimator=lambda i: 5)
        items = list(iter_pickups(p, ticks=2))
        assert {i.number for i in items} == {1, 3}  # 2nd tick is empty


class TestStreamCancel:
    def test_stream_stops_on_event(self) -> None:
        _, client = _make_client()
        p = IssuePoller(client, complexity_threshold=10,
                        complexity_estimator=lambda i: 5)

        async def run() -> list[int]:
            stop = asyncio.Event()
            collected: list[int] = []

            async def consume() -> None:
                async for issue in p.stream(interval_sec=0.05, stop=stop):
                    collected.append(issue.number)
                    if len(collected) >= 2:
                        stop.set()

            await asyncio.wait_for(consume(), timeout=2.0)
            return collected

        got = asyncio.run(run())
        assert sorted(got) == [1, 3]
