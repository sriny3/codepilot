"""Tests for PR builder utilities."""
import pytest

from codepilot.agents.pr_agent.builder import (
    build_pr_body,
    build_pr_title,
    extract_changed_files,
    format_test_summary,
    make_branch_name,
    make_commit_message,
)
from codepilot.memory.state import TestRunSummary


# ── make_branch_name ──────────────────────────────────────────────────────────


class TestMakeBranchName:
    def test_default_prefix(self) -> None:
        assert make_branch_name(42) == "codepilot/issue-42"

    def test_custom_prefix(self) -> None:
        assert make_branch_name(7, prefix="bot") == "bot/issue-7"

    def test_issue_id_in_name(self) -> None:
        name = make_branch_name(123)
        assert "123" in name

    def test_prefix_in_name(self) -> None:
        name = make_branch_name(1, prefix="mybot")
        assert name.startswith("mybot/")


# ── make_commit_message ───────────────────────────────────────────────────────


class TestMakeCommitMessage:
    def test_contains_issue_id(self) -> None:
        msg = make_commit_message(99, "add login")
        assert "99" in msg

    def test_contains_title(self) -> None:
        msg = make_commit_message(1, "fix null pointer")
        assert "fix null pointer" in msg

    def test_returns_string(self) -> None:
        assert isinstance(make_commit_message(1, "t"), str)


# ── build_pr_title ────────────────────────────────────────────────────────────


class TestBuildPrTitle:
    def test_contains_issue_id(self) -> None:
        assert "42" in build_pr_title(42, "something")

    def test_contains_title(self) -> None:
        assert "add feature" in build_pr_title(1, "add feature")

    def test_returns_string(self) -> None:
        assert isinstance(build_pr_title(1, "t"), str)


# ── format_test_summary ───────────────────────────────────────────────────────


class TestFormatTestSummary:
    def test_none_results(self) -> None:
        assert "No test results" in format_test_summary(None)

    def test_passed_count_shown(self) -> None:
        summary = TestRunSummary(passed=5, failed=0)
        assert "5 passed" in format_test_summary(summary)

    def test_failed_count_shown(self) -> None:
        summary = TestRunSummary(passed=0, failed=3)
        assert "3 failed" in format_test_summary(summary)

    def test_all_pass_no_failures_section(self) -> None:
        summary = TestRunSummary(passed=5, failed=0)
        assert "Failures" not in format_test_summary(summary)

    def test_failures_section_present(self) -> None:
        summary = TestRunSummary(
            passed=1,
            failed=1,
            failures=[{"test": "tests/test_x.py::test_foo", "reason": "AssertionError"}],
        )
        result = format_test_summary(summary)
        assert "Failures" in result
        assert "test_foo" in result

    def test_zero_passed_shows_zero(self) -> None:
        summary = TestRunSummary(passed=0, failed=0)
        assert "0 passed" in format_test_summary(summary)

    def test_returns_string(self) -> None:
        assert isinstance(format_test_summary(TestRunSummary()), str)


# ── build_pr_body ─────────────────────────────────────────────────────────────


class TestBuildPrBody:
    def test_contains_issue_id(self) -> None:
        body = build_pr_body(
            issue_id=5, issue_title="fix bug", proposed_diff=None, test_summary="0 passed"
        )
        assert "5" in body

    def test_contains_issue_title(self) -> None:
        body = build_pr_body(
            issue_id=1, issue_title="add widget", proposed_diff=None, test_summary="3 passed"
        )
        assert "add widget" in body

    def test_test_summary_embedded(self) -> None:
        body = build_pr_body(
            issue_id=1, issue_title="x", proposed_diff=None, test_summary="**Tests:** 5 passed"
        )
        assert "5 passed" in body

    def test_diff_section_present_when_diff_given(self) -> None:
        body = build_pr_body(
            issue_id=1, issue_title="x", proposed_diff="--- a/f\n+++ b/f\n+new line",
            test_summary="ok",
        )
        assert "```diff" in body

    def test_no_diff_section_when_diff_none(self) -> None:
        body = build_pr_body(
            issue_id=1, issue_title="x", proposed_diff=None, test_summary="ok"
        )
        assert "```diff" not in body

    def test_diff_truncated_when_too_long(self) -> None:
        long_diff = "+" + "x" * 5000
        body = build_pr_body(
            issue_id=1, issue_title="x", proposed_diff=long_diff, test_summary="ok",
            max_diff_chars=100,
        )
        assert "truncated" in body

    def test_diff_not_truncated_when_short(self) -> None:
        short_diff = "+one line"
        body = build_pr_body(
            issue_id=1, issue_title="x", proposed_diff=short_diff, test_summary="ok"
        )
        assert "truncated" not in body


# ── extract_changed_files ─────────────────────────────────────────────────────


class TestExtractChangedFiles:
    def test_single_file(self) -> None:
        diff = "--- a/src/foo.py\n+++ b/src/foo.py\n+new line"
        assert extract_changed_files(diff) == ["src/foo.py"]

    def test_multiple_files(self) -> None:
        diff = (
            "--- a/src/a.py\n+++ b/src/a.py\n+x\n"
            "--- a/src/b.py\n+++ b/src/b.py\n+y\n"
        )
        assert extract_changed_files(diff) == ["src/a.py", "src/b.py"]

    def test_empty_diff(self) -> None:
        assert extract_changed_files("") == []

    def test_no_plus_plus_plus_lines(self) -> None:
        assert extract_changed_files("--- a/foo.py\nsome context") == []

    def test_preserves_nested_paths(self) -> None:
        diff = "+++ b/a/b/c/d.py\n+content"
        assert extract_changed_files(diff) == ["a/b/c/d.py"]

    def test_returns_list(self) -> None:
        assert isinstance(extract_changed_files(""), list)
