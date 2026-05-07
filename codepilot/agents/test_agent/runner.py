"""Test runner types: configuration, protocol, and implementations."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from codepilot.sandbox.local import ExecuteResult

if TYPE_CHECKING:
    from codepilot.sandbox.local import LocalSandbox


@dataclass
class RunConfig:
    """Configuration for a single test execution."""

    command: str
    extra_files: list[str] = field(default_factory=list)
    timeout: float = 120.0


@runtime_checkable
class TestRunner(Protocol):
    """Interface satisfied by any test execution backend."""

    def run(
        self,
        sandbox: "LocalSandbox",
        *,
        command: str,
        timeout: float,
    ) -> ExecuteResult: ...


class SandboxTestRunner:
    """Runs the test command inside the sandbox via subprocess."""

    def run(
        self,
        sandbox: "LocalSandbox",
        *,
        command: str,
        timeout: float,
    ) -> ExecuteResult:
        return sandbox.execute(command, timeout=timeout)


class FakeTestRunner:
    """Deterministic test double. Returns a pre-configured ExecuteResult.

    Records the last command and timeout for assertion in tests.
    """

    def __init__(
        self,
        stdout: str = "",
        stderr: str = "",
        exit_code: int = 0,
        duration_ms: int = 100,
    ) -> None:
        self._result = ExecuteResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            duration_ms=duration_ms,
        )
        self.last_command: str | None = None
        self.last_timeout: float | None = None

    def run(
        self,
        sandbox: "LocalSandbox",
        *,
        command: str,
        timeout: float,
    ) -> ExecuteResult:
        self.last_command = command
        self.last_timeout = timeout
        return self._result
