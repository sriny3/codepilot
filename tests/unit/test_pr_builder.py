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
        assert make_branch_name(42, "Fix null pointer") == "codepilot/issue-42-fix-null-pointer"

    def test_custom_prefix(self) -> None:
        assert make_branch_name(7, "add feature", prefix="bot") == "bot/issue-7-add-feature"

    def test_slug_strips_special_chars(self) -> None:
        name = make_branch_name(1, "Fix: the auth (bug)!")
        assert name == "codepilot/issue-1-fix-the-auth-bug"

    def test_slug_truncated_to_40_chars(self) -> None:
        long_title = "a" * 60
        name = make_branch_name(1, long_title)
        slug = name.split("issue-1-")[1]
        assert len(slug) <= 40

    def test_issue_id_in_name(self) -> None:
        assert "123" in make_branch_name(123, "some title")

    def test_slug_is_kebab_case(self) -> None:
        name = make_branch_name(1, "Add dark mode support")
        assert "add-dark-mode-support" in name

    def test_empty_title_produces_valid_name(self) -> None:
        name = make_branch_name(1, "")
        assert not name.endswith("-")
        assert "issue-1" in name

    def test_special_chars_only_title_produces_valid_name(self) -> None:
        name = make_branch_name(1, "!!!")
        assert not name.endswith("-")
        assert "issue-1" in name

    def test_slug_truncation_no_trailing_hyphen(self) -> None:
        # title where the 40th char of slug falls on a hyphen
        title = "a" * 39 + " extra"
        name = make_branch_name(1, title)
        slug = name.split("issue-1-")[1]
        assert not slug.endswith("-")
        assert len(slug) <= 40


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

    def test_conventional_commit_format(self) -> None:
        msg = make_commit_message(99, "add login")
        assert msg.startswith("fix(#99):")


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


class TestBuildPrBodyApproach:
    def test_approach_section_present_when_provided(self) -> None:
        body = build_pr_body(
            issue_id=1, issue_title="fix", proposed_diff=None,
            test_summary="ok", approach="Used TF-IDF + Qdrant rerank."
        )
        assert "## Approach" in body
        assert "TF-IDF" in body

    def test_approach_section_absent_when_empty(self) -> None:
        body = build_pr_body(
            issue_id=1, issue_title="fix", proposed_diff=None,
            test_summary="ok", approach=""
        )
        assert "## Approach" not in body

    def test_approach_default_is_empty(self) -> None:
        body = build_pr_body(
            issue_id=1, issue_title="fix", proposed_diff=None, test_summary="ok"
        )
        assert "## Approach" not in body


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
