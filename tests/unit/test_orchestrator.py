"""Orchestrator pipeline tests."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from codepilot.agents.test_agent.runner import RunConfig
from codepilot.github_io.models import IssueRef
from codepilot.memory.state import TaskState, TestRunSummary, WorkingMemory
from codepilot.orchestrator.orchestrator import Orchestrator, _format_failure_hint


# ── Fake agents ────────────────────────────────────────────────────────────────


class _FakeExplorer:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, wm: WorkingMemory, repo_root: Path, issue_body: str) -> WorkingMemory:
        self.calls.append({"repo_root": repo_root, "issue_body": issue_body})
        wm.transition(TaskState.EXPLORING)
        wm.relevant_files = ["src/main.py"]
        return wm


class _FakeCoder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(
        self,
        wm: WorkingMemory,
        source_root: Path,
        issue_body: str,
        *,
        skill_prompt: str | None = None,
    ) -> WorkingMemory:
        self.calls.append({"source_root": source_root, "issue_body": issue_body,
                           "skill_prompt": skill_prompt})
        wm.transition(TaskState.IMPLEMENTING)
        wm.proposed_diff = "--- a/f\n+++ b/f\n+fix"
        return wm


class _FakeTestAgent:
    __test__ = False

    def __init__(self, *results: TestRunSummary) -> None:
        self._results = list(results) or [TestRunSummary(passed=1, failed=0)]
        self._idx = 0
        self.calls: list[RunConfig] = []

    def run(self, wm: WorkingMemory, config: RunConfig) -> WorkingMemory:
        self.calls.append(config)
        result = self._results[min(self._idx, len(self._results) - 1)]
        self._idx += 1
        wm.transition(TaskState.TESTING)
        wm.test_results = result
        return wm


class _FakePRAgent:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(
        self,
        wm: WorkingMemory,
        issue_title: str,
        *,
        pr_labels: tuple = (),
        reviewers: tuple = (),
    ) -> WorkingMemory:
        self.calls.append({"issue_title": issue_title, "pr_labels": pr_labels,
                           "reviewers": reviewers})
        wm.transition(TaskState.PR_OPENED)
        wm.notes.append("PR #1: https://github.com/acme/x/pull/1")
        return wm


# ── Fixtures ───────────────────────────────────────────────────────────────────

_ISSUE = IssueRef(
    number=42,
    title="fix login bug",
    body="The login endpoint returns 500.",
    labels=(),
    assignees=(),
    reporter="alice",
    repo="owner/repo",
    state="open",
    created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    url="https://github.com/owner/repo/issues/42",
)


@pytest.fixture()
def source_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


@pytest.fixture()
def wm() -> WorkingMemory:
    return WorkingMemory(issue_id=42, repo="owner/repo", trace_id="trace-1")


def _make_orchestrator(
    *,
    explorer: _FakeExplorer | None = None,
    coder: _FakeCoder | None = None,
    test_results: list[TestRunSummary] | None = None,
    pr_agent: _FakePRAgent | None = None,
    max_retries: int = 3,
    run_config: RunConfig | None = None,
) -> tuple[Orchestrator, _FakeExplorer, _FakeCoder, _FakeTestAgent, _FakePRAgent]:
    e = explorer or _FakeExplorer()
    c = coder or _FakeCoder()
    t = _FakeTestAgent(*(test_results or [TestRunSummary(passed=5, failed=0)]))
    p = pr_agent or _FakePRAgent()
    orch = Orchestrator(e, c, t, p, max_retries=max_retries, run_config=run_config)
    return orch, e, c, t, p


# ── _format_failure_hint ──────────────────────────────────────────────────────


class TestFormatFailureHint:
    def test_none_results(self) -> None:
        hint = _format_failure_hint(None)
        assert "failed" in hint.lower()

    def test_no_failures_list(self) -> None:
        hint = _format_failure_hint(TestRunSummary(passed=0, failed=2, failures=[]))
        assert "2" in hint

    def test_failures_included(self) -> None:
        summary = TestRunSummary(
            passed=0, failed=1,
            failures=[{"test": "tests/test_x.py::test_foo", "reason": "AssertionError"}],
        )
        hint = _format_failure_hint(summary)
        assert "test_foo" in hint
        assert "AssertionError" in hint

    def test_capped_at_five_failures(self) -> None:
        failures = [{"test": f"t::test_{i}", "reason": "err"} for i in range(10)]
        hint = _format_failure_hint(TestRunSummary(passed=0, failed=10, failures=failures))
        assert hint.count("FAILED") <= 5


# ── Orchestrator.run_issue ────────────────────────────────────────────────────


class TestOrchestrator:
    def test_happy_path_state_is_done(
        self, wm: WorkingMemory, source_root: Path
    ) -> None:
        orch, *_ = _make_orchestrator()
        orch.run_issue(wm, _ISSUE, source_root=source_root)
        assert wm.state == TaskState.DONE

    def test_returns_same_wm(self, wm: WorkingMemory, source_root: Path) -> None:
        orch, *_ = _make_orchestrator()
        result = orch.run_issue(wm, _ISSUE, source_root=source_root)
        assert result is wm

    def test_explorer_called(self, wm: WorkingMemory, source_root: Path) -> None:
        orch, explorer, *_ = _make_orchestrator()
        orch.run_issue(wm, _ISSUE, source_root=source_root)
        assert len(explorer.calls) == 1

    def test_coder_called_with_issue_body(
        self, wm: WorkingMemory, source_root: Path
    ) -> None:
        orch, _, coder, *_ = _make_orchestrator()
        orch.run_issue(wm, _ISSUE, source_root=source_root)
        assert coder.calls[0]["issue_body"] == _ISSUE.body

    def test_test_agent_called(self, wm: WorkingMemory, source_root: Path) -> None:
        orch, _, _, test_agent, _ = _make_orchestrator()
        orch.run_issue(wm, _ISSUE, source_root=source_root)
        assert len(test_agent.calls) >= 1

    def test_pr_agent_called_when_tests_pass(
        self, wm: WorkingMemory, source_root: Path
    ) -> None:
        orch, _, _, _, pr_agent = _make_orchestrator()
        orch.run_issue(wm, _ISSUE, source_root=source_root)
        assert len(pr_agent.calls) == 1

    def test_pr_agent_not_called_when_always_failing(
        self, wm: WorkingMemory, source_root: Path
    ) -> None:
        fail = TestRunSummary(passed=0, failed=1)
        orch, _, _, _, pr_agent = _make_orchestrator(
            test_results=[fail] * 10, max_retries=2
        )
        orch.run_issue(wm, _ISSUE, source_root=source_root)
        assert len(pr_agent.calls) == 0

    def test_retry_on_failure_calls_coder_again(
        self, wm: WorkingMemory, source_root: Path
    ) -> None:
        fail = TestRunSummary(passed=0, failed=1)
        ok = TestRunSummary(passed=3, failed=0)
        orch, _, coder, *_ = _make_orchestrator(test_results=[fail, ok])
        orch.run_issue(wm, _ISSUE, source_root=source_root)
        assert len(coder.calls) == 2  # initial + 1 retry

    def test_retry_count_incremented(
        self, wm: WorkingMemory, source_root: Path
    ) -> None:
        fail = TestRunSummary(passed=0, failed=1)
        ok = TestRunSummary(passed=3, failed=0)
        orch, *_ = _make_orchestrator(test_results=[fail, ok])
        orch.run_issue(wm, _ISSUE, source_root=source_root)
        assert wm.retry_count == 1

    def test_fail_after_max_retries(
        self, wm: WorkingMemory, source_root: Path
    ) -> None:
        fail = TestRunSummary(passed=0, failed=1)
        orch, *_ = _make_orchestrator(test_results=[fail] * 10, max_retries=2)
        orch.run_issue(wm, _ISSUE, source_root=source_root)
        assert wm.state == TaskState.FAILED

    def test_no_extra_retry_when_tests_pass_first(
        self, wm: WorkingMemory, source_root: Path
    ) -> None:
        orch, _, coder, *_ = _make_orchestrator(
            test_results=[TestRunSummary(passed=5, failed=0)]
        )
        orch.run_issue(wm, _ISSUE, source_root=source_root)
        assert len(coder.calls) == 1  # only the initial call, no retry

    def test_failure_hint_passed_as_skill_prompt(
        self, wm: WorkingMemory, source_root: Path
    ) -> None:
        fail = TestRunSummary(
            passed=0, failed=1,
            failures=[{"test": "tests/t.py::test_x", "reason": "AssertionError"}],
        )
        ok = TestRunSummary(passed=1, failed=0)
        orch, _, coder, *_ = _make_orchestrator(test_results=[fail, ok])
        orch.run_issue(wm, _ISSUE, source_root=source_root)
        retry_call = coder.calls[1]
        assert retry_call["skill_prompt"] is not None
        assert "test_x" in retry_call["skill_prompt"]

    def test_issue_title_passed_to_pr_agent(
        self, wm: WorkingMemory, source_root: Path
    ) -> None:
        orch, _, _, _, pr_agent = _make_orchestrator()
        orch.run_issue(wm, _ISSUE, source_root=source_root)
        assert pr_agent.calls[0]["issue_title"] == _ISSUE.title

    def test_pr_labels_forwarded(self, wm: WorkingMemory, source_root: Path) -> None:
        orch, _, _, _, pr_agent = _make_orchestrator()
        orch.run_issue(wm, _ISSUE, source_root=source_root, pr_labels=("bug",))
        assert "bug" in pr_agent.calls[0]["pr_labels"]

    def test_custom_run_config_passed_to_test_agent(
        self, wm: WorkingMemory, source_root: Path
    ) -> None:
        cfg = RunConfig(command="pytest tests/ -x", timeout=30.0)
        orch, _, _, test_agent, _ = _make_orchestrator(run_config=cfg)
        orch.run_issue(wm, _ISSUE, source_root=source_root)
        assert test_agent.calls[0].command == "pytest tests/ -x"

    def test_default_run_config_is_pytest(
        self, wm: WorkingMemory, source_root: Path
    ) -> None:
        orch, _, _, test_agent, _ = _make_orchestrator()
        orch.run_issue(wm, _ISSUE, source_root=source_root)
        assert "pytest" in test_agent.calls[0].command

    def test_agent_exception_marks_wm_failed(
        self, wm: WorkingMemory, source_root: Path
    ) -> None:
        class _BrokenCoder:
            def run(self, wm: WorkingMemory, *a: object, **kw: object) -> WorkingMemory:
                wm.transition(TaskState.IMPLEMENTING)
                raise RuntimeError("LLM timeout")

        orch = Orchestrator(_FakeExplorer(), _BrokenCoder(), _FakeTestAgent(), _FakePRAgent())
        orch.run_issue(wm, _ISSUE, source_root=source_root)
        assert wm.state == TaskState.FAILED
