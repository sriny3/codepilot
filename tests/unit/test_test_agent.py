"""TestAgent integration tests."""
from pathlib import Path

import pytest

from codepilot.agents.test_agent.agent import TestAgent
from codepilot.agents.test_agent.runner import FakeTestRunner, RunConfig, SandboxTestRunner
from codepilot.memory.state import InvalidTransition, TaskState, WorkingMemory
from codepilot.sandbox.local import LocalSandbox


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture()
def source_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_auth.py").write_text("def test_login(): assert True\n")
    (root / "src").mkdir()
    (root / "src" / "auth.py").write_text("def login(): return True\n")
    return root


@pytest.fixture()
def sandbox(tmp_path: Path) -> LocalSandbox:
    sb = LocalSandbox(tmp_path / "sandbox")
    sb.write_file("src/auth.py", "def login(): return True\n")
    return sb


@pytest.fixture()
def wm() -> WorkingMemory:
    w = WorkingMemory(issue_id=1, repo="owner/repo", trace_id="t1")
    w.transition(TaskState.EXPLORING)
    w.transition(TaskState.IMPLEMENTING)
    return w


_PASS_OUT = "1 passed in 0.1s"
_FAIL_OUT = (
    "FAILED tests/test_auth.py::test_login - AssertionError: got False\n"
    "1 failed in 0.2s"
)


# ── TestAgent.run ──────────────────────────────────────────────────────────────


class TestTestAgent:
    def test_transitions_to_testing(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        TestAgent(sandbox, source_root, runner=FakeTestRunner(stdout=_PASS_OUT)).run(
            wm, RunConfig(command="pytest")
        )
        assert wm.state == TaskState.TESTING

    def test_test_results_populated(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        TestAgent(sandbox, source_root, runner=FakeTestRunner(stdout=_PASS_OUT)).run(
            wm, RunConfig(command="pytest")
        )
        assert wm.test_results is not None

    def test_passed_count_recorded(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        TestAgent(
            sandbox, source_root, runner=FakeTestRunner(stdout="3 passed in 0.5s")
        ).run(wm, RunConfig(command="pytest"))
        assert wm.test_results.passed == 3

    def test_failed_count_recorded(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        TestAgent(
            sandbox, source_root, runner=FakeTestRunner(stdout=_FAIL_OUT, exit_code=1)
        ).run(wm, RunConfig(command="pytest"))
        assert wm.test_results.failed == 1

    def test_failure_details_recorded(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        TestAgent(
            sandbox, source_root, runner=FakeTestRunner(stdout=_FAIL_OUT, exit_code=1)
        ).run(wm, RunConfig(command="pytest"))
        assert len(wm.test_results.failures) == 1
        assert "test_login" in wm.test_results.failures[0]["test"]

    def test_command_passed_to_runner(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        runner = FakeTestRunner()
        TestAgent(sandbox, source_root, runner=runner).run(
            wm, RunConfig(command="pytest tests/ -v")
        )
        assert runner.last_command == "pytest tests/ -v"

    def test_timeout_passed_to_runner(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        runner = FakeTestRunner()
        TestAgent(sandbox, source_root, runner=runner).run(
            wm, RunConfig(command="pytest", timeout=60.0)
        )
        assert runner.last_timeout == 60.0

    def test_extra_files_staged_in_sandbox(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        TestAgent(sandbox, source_root, runner=FakeTestRunner()).run(
            wm, RunConfig(command="pytest", extra_files=["tests/test_auth.py"])
        )
        assert sandbox.exists("tests/test_auth.py")

    def test_no_extra_files_leaves_sandbox_unchanged(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        TestAgent(sandbox, source_root, runner=FakeTestRunner()).run(
            wm, RunConfig(command="pytest")
        )
        assert not sandbox.exists("tests/test_auth.py")

    def test_returns_same_wm_object(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        result = TestAgent(sandbox, source_root, runner=FakeTestRunner()).run(
            wm, RunConfig(command="pytest")
        )
        assert result is wm

    def test_raises_invalid_transition_from_triaged(
        self, sandbox: LocalSandbox, source_root: Path
    ) -> None:
        bad_wm = WorkingMemory(issue_id=2, repo="owner/repo", trace_id="t2")
        with pytest.raises(InvalidTransition):
            TestAgent(sandbox, source_root, runner=FakeTestRunner()).run(
                bad_wm, RunConfig(command="pytest")
            )

    def test_raises_invalid_transition_from_exploring(
        self, sandbox: LocalSandbox, source_root: Path
    ) -> None:
        bad_wm = WorkingMemory(issue_id=3, repo="owner/repo", trace_id="t3")
        bad_wm.transition(TaskState.EXPLORING)
        with pytest.raises(InvalidTransition):
            TestAgent(sandbox, source_root, runner=FakeTestRunner()).run(
                bad_wm, RunConfig(command="pytest")
            )

    def test_default_runner_is_sandbox_runner(
        self, sandbox: LocalSandbox, source_root: Path
    ) -> None:
        agent = TestAgent(sandbox, source_root)
        assert isinstance(agent._runner, SandboxTestRunner)

    def test_all_pass_summary_has_zero_failed(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        TestAgent(
            sandbox, source_root, runner=FakeTestRunner(stdout="5 passed", exit_code=0)
        ).run(wm, RunConfig(command="pytest"))
        assert wm.test_results.failed == 0

    def test_framework_recorded_in_results(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        TestAgent(
            sandbox, source_root, runner=FakeTestRunner(stdout="5 passed\npytest")
        ).run(wm, RunConfig(command="pytest"))
        assert wm.test_results.framework == "pytest"
