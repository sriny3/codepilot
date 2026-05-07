"""Orchestrator — drives the full agent pipeline for a single issue."""
from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from codepilot.agents.test_agent.runner import RunConfig
from codepilot.github_io.models import IssueRef
from codepilot.memory.state import TaskState, TestRunSummary, WorkingMemory
from codepilot.observability import get_logger
from codepilot.observability.events import Event

_log = get_logger("orchestrator")


def _format_failure_hint(test_results: TestRunSummary | None) -> str:
    """Convert failed test results into a skill_prompt for the Coder."""
    if test_results is None or not test_results.failures:
        count = test_results.failed if test_results else 1
        return f"Tests failed ({count} failure(s)). Fix the failing tests."
    lines = ["Fix the following test failures:"]
    for failure in test_results.failures[:5]:
        lines.append(f"  FAILED {failure['test']}: {failure['reason']}")
    return "\n".join(lines)


class Orchestrator:
    """Drive RepoExplorer → Coder → TestAgent → PRAgent for one issue.

    The retry loop transitions TESTING → IMPLEMENTING up to ``max_retries``
    times when tests fail, passing failure details as a ``skill_prompt`` to
    the Coder. After ``max_retries`` exhausted, marks the task FAILED.

    All agents are injected for testability — any object with the right
    ``run`` signature satisfies the contract.
    """

    def __init__(
        self,
        repo_explorer: Any,
        coder: Any,
        test_agent: Any,
        pr_agent: Any,
        *,
        max_retries: int = 3,
        run_config: RunConfig | None = None,
    ) -> None:
        self._repo_explorer = repo_explorer
        self._coder = coder
        self._test_agent = test_agent
        self._pr_agent = pr_agent
        self._max_retries = max_retries
        self._run_config = run_config or RunConfig(command="pytest")

    def run_issue(
        self,
        wm: WorkingMemory,
        issue_ref: IssueRef,
        *,
        source_root: Path,
        pr_labels: Sequence[str] = (),
        reviewers: Sequence[str] = (),
    ) -> WorkingMemory:
        """Run the full pipeline for one issue. Returns wm in terminal or PR_OPENED state.

        Steps:
        1. RepoExplorer: TRIAGED → EXPLORING.
        2. Coder: EXPLORING → IMPLEMENTING.
        3. TestAgent: IMPLEMENTING → TESTING.
        4. If tests fail and retries remain: bump_retry, Coder retries TESTING → IMPLEMENTING.
        5. If tests fail after max_retries: FAILED.
        6. PRAgent: TESTING → PR_OPENED.
        7. Transition PR_OPENED → DONE.
        """
        _started = time.monotonic()
        try:
            self._repo_explorer.run(wm, source_root, issue_ref.body)
            self._coder.run(wm, source_root, issue_ref.body)

            for attempt in range(self._max_retries + 1):
                self._test_agent.run(wm, self._run_config)

                if wm.test_results is not None and wm.test_results.failed == 0:
                    break

                if attempt < self._max_retries:
                    wm.bump_retry()
                    hint = _format_failure_hint(wm.test_results)
                    self._coder.run(wm, source_root, issue_ref.body, skill_prompt=hint)
                else:
                    wm.fail("max retries exceeded")
                    return wm

            self._pr_agent.run(
                wm,
                issue_ref.title,
                pr_labels=pr_labels,
                reviewers=reviewers,
            )
            wm.transition(TaskState.DONE)
            _log.info(
                Event.TASK_COMPLETE,
                outcome="DONE",
                duration_ms=int((time.monotonic() - _started) * 1000),
                repo=wm.repo,
                issue_id=wm.issue_id,
                trace_id=wm.trace_id,
            )

        except Exception as exc:
            if not wm.is_terminal():
                wm.fail(str(exc))
            _log.error(
                "orchestrator.error",
                error=str(exc),
                repo=wm.repo,
                issue_id=wm.issue_id,
                trace_id=wm.trace_id,
            )

        return wm
