"""Parse pytest terminal output into a TestRunSummary."""
from __future__ import annotations

import re

from codepilot.memory.state import TestRunSummary

# "5 passed", "3 passed, 2 failed", "1 error"
_PASSED_RE = re.compile(r"(\d+)\s+passed")
_FAILED_RE = re.compile(r"(\d+)\s+(?:failed|error)")

# "FAILED tests/foo.py::TestClass::test_method - AssertionError: message"
_FAILURE_LINE_RE = re.compile(r"^FAILED\s+(\S+)\s+-\s+(.+)$", re.MULTILINE)


def parse_pytest_output(stdout: str, stderr: str, exit_code: int) -> TestRunSummary:
    """Parse pytest terminal output into a TestRunSummary.

    Handles:
    - Standard summary line: "N passed", "M failed", "K error"
    - FAILED lines for per-failure details
    - Fallback when exit_code != 0 but no parseable counts → failed=1
    - Framework detection from pytest-specific markers
    """
    combined = stdout + "\n" + stderr

    passed_m = _PASSED_RE.search(combined)
    failed_m = _FAILED_RE.search(combined)

    passed = int(passed_m.group(1)) if passed_m else 0
    failed = int(failed_m.group(1)) if failed_m else 0

    if not passed_m and not failed_m and exit_code != 0:
        failed = 1  # something failed but no parseable summary

    failures: list[dict] = []
    for m in _FAILURE_LINE_RE.finditer(combined):
        failures.append({"test": m.group(1), "reason": m.group(2).strip()})

    combined_lower = combined.lower()
    framework: str | None = None
    if "pytest" in combined_lower or "PASSED" in combined or "FAILED" in combined:
        framework = "pytest"

    return TestRunSummary(
        passed=passed,
        failed=failed,
        framework=framework,
        failures=failures,
    )
