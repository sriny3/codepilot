from datetime import datetime, timedelta, timezone

import pytest

from codepilot.memory.episodic import (
    EpisodicStore,
    SessionSummary,
    TaskOutcome,
    new_session_id,
    now_utc,
)


def _outcome(issue_id: int, outcome: str = "DONE") -> TaskOutcome:
    return TaskOutcome(
        issue_id=issue_id, repo="acme/x", task_type="bug_fix",
        files_modified=["src/a.py"], outcome=outcome,
        duration_ms=1234,
    )


def _session(sid: str, ended: datetime, tasks: list[TaskOutcome]) -> SessionSummary:
    return SessionSummary(
        session_id=sid,
        started_at=ended - timedelta(minutes=10),
        ended_at=ended,
        tasks=tasks,
    )


class TestTaskRecords:
    def test_record_and_read_back(self) -> None:
        s = EpisodicStore()
        sid = new_session_id()
        s.record_task(session_id=sid, outcome=_outcome(1))
        s.record_task(session_id=sid, outcome=_outcome(2, "FAILED"))
        recs = s.task_records(sid)
        assert {r.issue_id for r in recs} == {1, 2}

    def test_isolation_across_sessions(self) -> None:
        s = EpisodicStore()
        a, b = new_session_id(), new_session_id()
        s.record_task(session_id=a, outcome=_outcome(1))
        s.record_task(session_id=b, outcome=_outcome(2))
        assert {r.issue_id for r in s.task_records(a)} == {1}
        assert {r.issue_id for r in s.task_records(b)} == {2}


class TestSessionRoundtrip:
    def test_write_get(self) -> None:
        s = EpisodicStore()
        ses = _session("S1", now_utc(), [_outcome(7)])
        s.write_session(ses)
        got = s.get_session("S1")
        assert got is not None
        assert got.session_id == "S1"
        assert got.tasks[0].issue_id == 7

    def test_get_unknown_returns_none(self) -> None:
        s = EpisodicStore()
        assert s.get_session("missing") is None


class TestRecentSessions:
    def test_orders_by_ended_at_desc(self) -> None:
        s = EpisodicStore()
        base = now_utc()
        for i in range(5):
            s.write_session(_session(
                f"S{i}", base - timedelta(hours=i),
                [_outcome(i + 100)],
            ))
        recent = s.recent_sessions(n=3)
        assert [r.session_id for r in recent] == ["S0", "S1", "S2"]

    def test_clamps_to_available(self) -> None:
        s = EpisodicStore()
        s.write_session(_session("only", now_utc(), [_outcome(1)]))
        recent = s.recent_sessions(n=10)
        assert len(recent) == 1


class TestRecentlyFailed:
    def test_collects_failures_from_window(self) -> None:
        s = EpisodicStore()
        base = now_utc()
        s.write_session(_session("oldest", base - timedelta(hours=10),
                                 [_outcome(1, "FAILED")]))
        s.write_session(_session("mid", base - timedelta(hours=1),
                                 [_outcome(2, "FAILED"), _outcome(3, "DONE")]))
        s.write_session(_session("latest", base,
                                 [_outcome(4, "FAILED")]))
        ids = s.recently_failed_issue_ids(n=2)
        assert ids == {2, 4}  # window of 2 latest sessions

    def test_done_only_returns_empty(self) -> None:
        s = EpisodicStore()
        s.write_session(_session("S", now_utc(), [_outcome(1, "DONE")]))
        assert s.recently_failed_issue_ids() == set()
