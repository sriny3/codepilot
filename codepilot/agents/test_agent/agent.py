"""TestAgent — runs the project test suite in the sandbox and records results."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from codepilot.agents.test_agent.parser import parse_pytest_output
from codepilot.agents.test_agent.runner import RunConfig, SandboxTestRunner, TestRunner
from codepilot.memory.state import TaskState, WorkingMemory
from codepilot.observability import get_logger
from codepilot.observability.events import Event

if TYPE_CHECKING:
    from codepilot.sandbox.local import LocalSandbox

_log = get_logger("test_agent")


class TestAgent:
    """Stage extra files, run the test command, parse output, update wm.

    Transitions WorkingMemory from IMPLEMENTING → TESTING and populates
    ``wm.test_results`` with pass/fail counts and per-failure details.
    """

    __test__ = False  # prevent pytest from collecting this class

    def __init__(
        self,
        sandbox: "LocalSandbox",
        source_root: Path,
        *,
        runner: TestRunner | None = None,
    ) -> None:
        self._sandbox = sandbox
        self._source_root = source_root
        self._runner: TestRunner = runner if runner is not None else SandboxTestRunner()

    def run(self, wm: WorkingMemory, config: RunConfig) -> WorkingMemory:
        """Run tests, parse results, store in wm, return wm.

        Steps:
        1. Transition IMPLEMENTING → TESTING.
        2. Copy config.extra_files from source_root into sandbox.
        3. Execute config.command via the runner.
        4. Parse stdout/stderr/exit_code into TestRunSummary.
        5. Store summary in wm.test_results.
        6. Emit Event.TESTS_RUN.
        7. Return wm.
        """
        wm.transition(TaskState.TESTING)

        if config.extra_files:
            self._sandbox.copy_subset(self._source_root, config.extra_files)

        result = self._runner.run(
            self._sandbox,
            command=config.command,
            timeout=config.timeout,
        )

        summary = parse_pytest_output(result.stdout, result.stderr, result.exit_code)
        wm.test_results = summary

        _log.info(
            Event.TESTS_RUN,
            repo=wm.repo,
            issue_id=wm.issue_id,
            passed=summary.passed,
            failed=summary.failed,
            framework=summary.framework,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
        )

        return wm
