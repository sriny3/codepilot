"""Pure utility functions for constructing PR metadata from WorkingMemory."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from codepilot.memory.state import TestRunSummary

_DIFF_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)


def make_branch_name(issue_id: int, title: str, *, prefix: str = "codepilot") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40]
    return f"{prefix}/issue-{issue_id}-{slug}"


def make_commit_message(issue_id: int, issue_title: str) -> str:
    return f"fix(#{issue_id}): {issue_title}"


def build_pr_title(issue_id: int, issue_title: str) -> str:
    return f"fix: #{issue_id} {issue_title}"


def format_test_summary(test_results: "TestRunSummary | None") -> str:
    if test_results is None:
        return "No test results."
    parts: list[str] = []
    if test_results.passed:
        parts.append(f"{test_results.passed} passed")
    if test_results.failed:
        parts.append(f"{test_results.failed} failed")
    summary_line = ", ".join(parts) if parts else "0 passed"
    lines = [f"**Tests:** {summary_line}"]
    if test_results.failures:
        lines.append("")
        lines.append("**Failures:**")
        for f in test_results.failures:
            lines.append(f"- `{f['test']}`: {f['reason']}")
    return "\n".join(lines)


def build_pr_body(
    *,
    issue_id: int,
    issue_title: str,
    proposed_diff: str | None,
    test_summary: str,
    approach: str = "",
    max_diff_chars: int = 3000,
) -> str:
    approach_section = f"\n\n## Approach\n{approach}" if approach else ""
    diff_section = ""
    if proposed_diff:
        truncated = proposed_diff[:max_diff_chars]
        if len(proposed_diff) > max_diff_chars:
            truncated += "\n... (truncated)"
        diff_section = f"\n\n## Diff\n```diff\n{truncated}\n```"
    return (
        f"Fixes #{issue_id}: {issue_title}\n\n"
        f"## Test Results\n{test_summary}"
        f"{approach_section}"
        f"{diff_section}"
    )


def extract_changed_files(diff_text: str) -> list[str]:
    """Return sandbox-relative paths from unified diff ``+++ b/<path>`` headers."""
    return [m.group(1) for m in _DIFF_FILE_RE.finditer(diff_text)]
