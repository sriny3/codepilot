import pytest
from pydantic import ValidationError

from codepilot.memory.state import (
    TERMINAL_STATES,
    TRANSITIONS,
    InvalidTransition,
    TaskState,
    TestRunSummary,
    WorkingMemory,
    WorkingMemoryRegistry,
)


def _wm(state: TaskState = TaskState.TRIAGED) -> WorkingMemory:
    wm = WorkingMemory(issue_id=1, repo="acme/x", trace_id="t-1")
    wm.state = state
    return wm


class TestConstruction:
    def test_defaults(self) -> None:
        wm = WorkingMemory(issue_id=42, repo="acme/x", trace_id="abc")
        assert wm.state == TaskState.TRIAGED
        assert wm.retry_count == 0
        assert wm.relevant_files == []
        assert wm.test_results is None

    def test_negative_retry_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WorkingMemory(issue_id=1, repo="r", trace_id="t", retry_count=-1)


class TestTransitions:
    @pytest.mark.parametrize(
        "src,dst",
        [
            (TaskState.TRIAGED, TaskState.EXPLORING),
            (TaskState.EXPLORING, TaskState.IMPLEMENTING),
            (TaskState.IMPLEMENTING, TaskState.TESTING),
            (TaskState.TESTING, TaskState.PR_OPENED),
            (TaskState.PR_OPENED, TaskState.DONE),
        ],
    )
    def test_happy_path(self, src: TaskState, dst: TaskState) -> None:
        wm = _wm(src)
        wm.transition(dst)
        assert wm.state == dst

    def test_self_loop_only_allowed_in_implementing(self) -> None:
        # Implementing → Implementing is allowed (retry within coder loop).
        wm = _wm(TaskState.IMPLEMENTING)
        wm.transition(TaskState.IMPLEMENTING)
        # Other self-loops illegal.
        wm = _wm(TaskState.EXPLORING)
        with pytest.raises(InvalidTransition):
            wm.transition(TaskState.EXPLORING)

    def test_testing_back_to_implementing(self) -> None:
        # Failing tests bounce back to Coder.
        wm = _wm(TaskState.TESTING)
        wm.transition(TaskState.IMPLEMENTING)
        assert wm.state == TaskState.IMPLEMENTING

    @pytest.mark.parametrize(
        "src,dst",
        [
            (TaskState.TRIAGED, TaskState.PR_OPENED),
            (TaskState.TRIAGED, TaskState.DONE),
            (TaskState.EXPLORING, TaskState.PR_OPENED),
            (TaskState.PR_OPENED, TaskState.IMPLEMENTING),
            (TaskState.DONE, TaskState.EXPLORING),
        ],
    )
    def test_illegal_edges_raise(self, src: TaskState, dst: TaskState) -> None:
        wm = _wm(src)
        with pytest.raises(InvalidTransition):
            wm.transition(dst)

    def test_terminal_blocks_all(self) -> None:
        for terminal in TERMINAL_STATES:
            wm = _wm(terminal)
            with pytest.raises(InvalidTransition):
                wm.transition(TaskState.EXPLORING)

    def test_fail_from_anywhere(self) -> None:
        for src in [TaskState.TRIAGED, TaskState.EXPLORING,
                    TaskState.IMPLEMENTING, TaskState.TESTING,
                    TaskState.PR_OPENED]:
            wm = _wm(src).fail("something broke")
            assert wm.state == TaskState.FAILED
            assert any("FAILED" in n for n in wm.notes)

    def test_fail_idempotent_on_terminal(self) -> None:
        wm = _wm(TaskState.DONE).fail("nope")
        assert wm.state == TaskState.DONE  # no-op, no exception


class TestTransitionsTable:
    def test_every_state_in_table(self) -> None:
        assert set(TaskState) == set(TRANSITIONS)


class TestSubagentSnapshot:
    def test_excludes_proposed_diff_and_test_results(self) -> None:
        wm = _wm(TaskState.IMPLEMENTING)
        wm.proposed_diff = "diff contents"
        wm.test_results = TestRunSummary(passed=1, failed=0)
        wm.relevant_files = ["src/a.py"]
        snap = wm.for_subagent()
        assert "proposed_diff" not in snap
        assert "test_results" not in snap
        assert snap["relevant_files"] == ["src/a.py"]
        assert snap["state"] == "IMPLEMENTING"


class TestRegistry:
    def test_open_get_close(self) -> None:
        r = WorkingMemoryRegistry()
        wm = r.open(issue_id=7, repo="acme/x", trace_id="t-7")
        assert 7 in r
        assert r.get(7) is wm
        wm.fail("done with it")
        r.close(7)
        assert 7 not in r

    def test_double_open_rejected(self) -> None:
        r = WorkingMemoryRegistry()
        r.open(issue_id=1, repo="r", trace_id="t")
        with pytest.raises(ValueError, match="already open"):
            r.open(issue_id=1, repo="r", trace_id="t")

    def test_close_non_terminal_rejected(self) -> None:
        r = WorkingMemoryRegistry()
        r.open(issue_id=1, repo="r", trace_id="t")
        with pytest.raises(InvalidTransition):
            r.close(1)

    def test_close_unknown_no_op(self) -> None:
        r = WorkingMemoryRegistry()
        r.close(99)  # silent
