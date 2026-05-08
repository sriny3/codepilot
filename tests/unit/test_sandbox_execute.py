"""Execute tests: timeout, stdout/stderr capture, exit-code propagation, guardrail enforcement."""
from pathlib import Path

import pytest

from codepilot.sandbox.local import ExecuteResult, ExecuteTimeout, LocalSandbox
from codepilot.guardrails.shell import ShellGuard, ShellRule
from codepilot.guardrails.base import Decision


@pytest.fixture()
def sandbox(tmp_path: Path) -> LocalSandbox:
    root = tmp_path / "sandbox"
    root.mkdir()
    return LocalSandbox(root)


# ── Basic execution ────────────────────────────────────────────────────────────


class TestBasicExecution:
    def test_stdout_captured(self, sandbox: LocalSandbox) -> None:
        result = sandbox.execute('python -c "print(\'hello\')"')
        assert "hello" in result.stdout
        assert result.exit_code == 0

    def test_stderr_captured(self, sandbox: LocalSandbox) -> None:
        result = sandbox.execute(
            'python -c "import sys; print(\'err\', file=sys.stderr)"'
        )
        assert "err" in result.stderr

    def test_exit_code_propagated_on_success(self, sandbox: LocalSandbox) -> None:
        result = sandbox.execute("python -c \"import sys; sys.exit(0)\"")
        assert result.exit_code == 0
        assert result.success is True

    def test_exit_code_propagated_on_failure(self, sandbox: LocalSandbox) -> None:
        result = sandbox.execute("python -c \"import sys; sys.exit(42)\"")
        assert result.exit_code == 42
        assert result.success is False

    def test_exit_code_1(self, sandbox: LocalSandbox) -> None:
        result = sandbox.execute("python -c \"import sys; sys.exit(1)\"")
        assert result.exit_code == 1

    def test_both_stdout_and_stderr(self, sandbox: LocalSandbox) -> None:
        result = sandbox.execute(
            'python -c "import sys; print(\'out\'); print(\'err\', file=sys.stderr)"'
        )
        assert "out" in result.stdout
        assert "err" in result.stderr


# ── ExecuteResult ──────────────────────────────────────────────────────────────


class TestExecuteResult:
    def test_is_frozen_dataclass(self, sandbox: LocalSandbox) -> None:
        result = sandbox.execute('python -c "pass"')
        assert isinstance(result, ExecuteResult)

    def test_duration_ms_is_positive(self, sandbox: LocalSandbox) -> None:
        result = sandbox.execute('python -c "pass"')
        assert result.duration_ms >= 0

    def test_success_property(self) -> None:
        ok = ExecuteResult(stdout="", stderr="", exit_code=0, duration_ms=5)
        fail = ExecuteResult(stdout="", stderr="", exit_code=1, duration_ms=5)
        assert ok.success is True
        assert fail.success is False


# ── Timeout ────────────────────────────────────────────────────────────────────


class TestTimeout:
    def test_timeout_raises_execute_timeout(self, sandbox: LocalSandbox) -> None:
        with pytest.raises(ExecuteTimeout) as exc_info:
            sandbox.execute(
                'python -c "import time; time.sleep(30)"',
                timeout=0.5,
            )
        assert exc_info.value.timeout == 0.5

    def test_execute_timeout_has_cmd(self, sandbox: LocalSandbox) -> None:
        cmd = 'python -c "import time; time.sleep(30)"'
        with pytest.raises(ExecuteTimeout) as exc_info:
            sandbox.execute(cmd, timeout=0.5)
        assert exc_info.value.cmd == cmd

    def test_execute_timeout_is_timeout_error(self) -> None:
        exc = ExecuteTimeout("sleep", 1.0)
        assert isinstance(exc, TimeoutError)

    def test_fast_command_does_not_timeout(self, sandbox: LocalSandbox) -> None:
        result = sandbox.execute('python -c "pass"', timeout=30.0)
        assert result.exit_code == 0


# ── Working directory ──────────────────────────────────────────────────────────


class TestCwd:
    def test_cwd_defaults_to_sandbox_root(self, sandbox: LocalSandbox) -> None:
        sandbox.write_file("marker.txt", "found")
        result = sandbox.execute(
            'python -c "import os, pathlib; print(pathlib.Path(\'marker.txt\').exists())"'
        )
        assert "True" in result.stdout

    def test_cwd_subdirectory(self, sandbox: LocalSandbox) -> None:
        sandbox.write_file("sub/marker.txt", "here")
        result = sandbox.execute(
            'python -c "import pathlib; print(pathlib.Path(\'marker.txt\').exists())"',
            cwd="sub",
        )
        assert "True" in result.stdout

    def test_cwd_traversal_raises(self, sandbox: LocalSandbox) -> None:
        from codepilot.sandbox.local import SandboxEscapeError

        with pytest.raises(SandboxEscapeError):
            sandbox.execute('python -c "pass"', cwd="../../outside")


# ── Guardrail enforcement ──────────────────────────────────────────────────────


class TestGuardrailEnforcement:
    def test_blocked_command_raises_permission_error(self, sandbox: LocalSandbox) -> None:
        with pytest.raises(PermissionError):
            sandbox.execute(":(){:|:&};:")  # fork bomb → BLOCK

    def test_hitl_command_raises_permission_error(self, sandbox: LocalSandbox) -> None:
        with pytest.raises(PermissionError):
            sandbox.execute("rm -rf /tmp/x")  # → HITL

    def test_custom_guard_blocks_command(self, tmp_path: Path) -> None:
        extra = [ShellRule("block_echo", "echo", Decision.BLOCK, "no echo")]
        guard = ShellGuard(extra_rules=extra)
        sb = LocalSandbox(tmp_path / "sb", shell_guard=guard)
        with pytest.raises(PermissionError):
            sb.execute('echo hello')

    def test_benign_command_passes_guard(self, sandbox: LocalSandbox) -> None:
        result = sandbox.execute('python -c "print(1+1)"')
        assert result.exit_code == 0

    def test_permission_error_message_includes_rule(self, sandbox: LocalSandbox) -> None:
        with pytest.raises(PermissionError) as exc_info:
            sandbox.execute(":(){:|:&};:")
        assert "fork_bomb" in str(exc_info.value)

    def test_hitl_error_message_includes_approval_hint(self, sandbox: LocalSandbox) -> None:
        with pytest.raises(PermissionError) as exc_info:
            sandbox.execute("rm -rf ./build_artifacts")
        assert "HITL" in str(exc_info.value) or "approval" in str(exc_info.value).lower()
