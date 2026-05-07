"""FakeTestRunner and SandboxTestRunner contract tests."""
from pathlib import Path

from codepilot.agents.test_agent.runner import FakeTestRunner, SandboxTestRunner, TestRunner
from codepilot.sandbox.local import ExecuteResult, LocalSandbox


class TestFakeTestRunner:
    def test_returns_configured_stdout(self, tmp_path: Path) -> None:
        runner = FakeTestRunner(stdout="5 passed", exit_code=0)
        result = runner.run(LocalSandbox(tmp_path / "sb"), command="pytest", timeout=30.0)
        assert result.stdout == "5 passed"

    def test_returns_configured_exit_code(self, tmp_path: Path) -> None:
        runner = FakeTestRunner(exit_code=1)
        result = runner.run(LocalSandbox(tmp_path / "sb"), command="pytest", timeout=30.0)
        assert result.exit_code == 1

    def test_returns_configured_stderr(self, tmp_path: Path) -> None:
        runner = FakeTestRunner(stderr="collection error")
        result = runner.run(LocalSandbox(tmp_path / "sb"), command="pytest", timeout=30.0)
        assert result.stderr == "collection error"

    def test_records_last_command(self, tmp_path: Path) -> None:
        runner = FakeTestRunner()
        runner.run(LocalSandbox(tmp_path / "sb"), command="pytest tests/", timeout=30.0)
        assert runner.last_command == "pytest tests/"

    def test_records_last_timeout(self, tmp_path: Path) -> None:
        runner = FakeTestRunner()
        runner.run(LocalSandbox(tmp_path / "sb"), command="pytest", timeout=60.0)
        assert runner.last_timeout == 60.0

    def test_returns_execute_result_type(self, tmp_path: Path) -> None:
        runner = FakeTestRunner(stdout="3 passed", exit_code=0)
        result = runner.run(LocalSandbox(tmp_path / "sb"), command="pytest", timeout=30.0)
        assert isinstance(result, ExecuteResult)

    def test_default_exit_code_is_zero(self, tmp_path: Path) -> None:
        runner = FakeTestRunner()
        result = runner.run(LocalSandbox(tmp_path / "sb"), command="pytest", timeout=30.0)
        assert result.exit_code == 0

    def test_default_stdout_is_empty(self, tmp_path: Path) -> None:
        runner = FakeTestRunner()
        result = runner.run(LocalSandbox(tmp_path / "sb"), command="pytest", timeout=30.0)
        assert result.stdout == ""

    def test_satisfies_test_runner_protocol(self) -> None:
        assert isinstance(FakeTestRunner(), TestRunner)

    def test_sandbox_test_runner_satisfies_protocol(self) -> None:
        assert isinstance(SandboxTestRunner(), TestRunner)


class TestSandboxTestRunnerContract:
    def test_runs_command_and_captures_stdout(self, tmp_path: Path) -> None:
        sandbox = LocalSandbox(tmp_path / "sb")
        result = SandboxTestRunner().run(
            sandbox, command='python -c "print(\'hello\')"', timeout=10.0
        )
        assert "hello" in result.stdout
        assert result.exit_code == 0

    def test_exit_code_propagated(self, tmp_path: Path) -> None:
        sandbox = LocalSandbox(tmp_path / "sb")
        result = SandboxTestRunner().run(
            sandbox,
            command='python -c "import sys; sys.exit(1)"',
            timeout=10.0,
        )
        assert result.exit_code == 1

    def test_duration_ms_non_negative(self, tmp_path: Path) -> None:
        sandbox = LocalSandbox(tmp_path / "sb")
        result = SandboxTestRunner().run(
            sandbox, command='python -c "pass"', timeout=10.0
        )
        assert result.duration_ms >= 0

    def test_returns_execute_result_type(self, tmp_path: Path) -> None:
        sandbox = LocalSandbox(tmp_path / "sb")
        result = SandboxTestRunner().run(
            sandbox, command='python -c "pass"', timeout=10.0
        )
        assert isinstance(result, ExecuteResult)
