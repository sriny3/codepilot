"""Test runner @tool wrappers."""
from __future__ import annotations

import re
from pathlib import Path

from langchain_core.tools import tool

_FAILED_RE = re.compile(r"\b\d+\s+failed\b", re.IGNORECASE)


def _run_suite(sandbox_path: str, command: str, timeout: float):
    from codepilot.agents.test_agent.parser import parse_pytest_output
    from codepilot.agents.test_agent.runner import SandboxTestRunner
    from codepilot.sandbox.local import LocalSandbox

    sandbox = LocalSandbox(Path(sandbox_path))
    runner = SandboxTestRunner()
    execute_result = runner.run(sandbox, command=command, timeout=timeout)
    return parse_pytest_output(
        execute_result.stdout,
        execute_result.stderr,
        execute_result.exit_code,
    )


@tool
def run_tests(sandbox_path: str, command: str, timeout: float) -> dict:
    """Run the test suite in a sandbox directory. Returns passed/failed/failures."""
    try:
        result = _run_suite(sandbox_path, command, timeout)
        return {"passed": result.passed, "failed": result.failed, "failures": result.failures}
    except Exception as exc:
        return {"passed": 0, "failed": -1, "failures": [{"test": "runner", "reason": str(exc)}]}


@tool
def parse_test_output(raw_output: str, framework: str) -> dict:
    """Parse raw test output into structured results. Supports pytest and unittest."""
    from codepilot.agents.test_agent.parser import parse_pytest_output

    # Infer exit_code: detect "N failed" pattern to avoid false positives
    exit_code = 1 if _FAILED_RE.search(raw_output) else 0

    result = parse_pytest_output(raw_output, "", exit_code)
    return {
        "passed": result.passed,
        "failed": result.failed,
        "framework": framework,
        "failures": result.failures,
    }
