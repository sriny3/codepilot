"""pytest output parser tests."""
from codepilot.agents.test_agent.parser import parse_pytest_output
from codepilot.memory.state import TestRunSummary


class TestParseOutput:
    def test_all_passed(self) -> None:
        summary = parse_pytest_output("5 passed in 0.5s", "", 0)
        assert summary.passed == 5
        assert summary.failed == 0

    def test_some_failed(self) -> None:
        summary = parse_pytest_output("3 passed, 2 failed in 1.0s", "", 1)
        assert summary.passed == 3
        assert summary.failed == 2

    def test_error_counted_as_failed(self) -> None:
        summary = parse_pytest_output("1 error", "", 1)
        assert summary.failed == 1

    def test_mixed_passed_and_errors(self) -> None:
        summary = parse_pytest_output("2 passed, 1 error", "", 1)
        assert summary.passed == 2
        assert summary.failed == 1

    def test_empty_output_exit_zero_no_failures(self) -> None:
        summary = parse_pytest_output("", "", 0)
        assert summary.passed == 0
        assert summary.failed == 0

    def test_empty_output_exit_nonzero_fallback_to_one_failure(self) -> None:
        summary = parse_pytest_output("", "", 1)
        assert summary.failed == 1

    def test_failure_lines_extracted(self) -> None:
        stdout = (
            "FAILED tests/test_auth.py::TestAuth::test_login - AssertionError: got False\n"
            "FAILED tests/test_auth.py::TestAuth::test_logout - AssertionError: got None\n"
        )
        summary = parse_pytest_output(stdout, "", 1)
        assert len(summary.failures) == 2

    def test_failure_test_name_recorded(self) -> None:
        stdout = "FAILED tests/foo.py::test_bar - ValueError: bad\n"
        summary = parse_pytest_output(stdout, "", 1)
        assert summary.failures[0]["test"] == "tests/foo.py::test_bar"

    def test_failure_reason_recorded(self) -> None:
        stdout = "FAILED tests/foo.py::test_bar - AssertionError: expected True\n"
        summary = parse_pytest_output(stdout, "", 1)
        assert "AssertionError" in summary.failures[0]["reason"]

    def test_framework_detected_from_pytest_keyword(self) -> None:
        summary = parse_pytest_output("5 passed\npytest", "", 0)
        assert summary.framework == "pytest"

    def test_framework_detected_from_failed_marker(self) -> None:
        summary = parse_pytest_output("FAILED tests/foo.py::test_bar - AssertionError", "", 1)
        assert summary.framework == "pytest"

    def test_framework_detected_from_passed_marker(self) -> None:
        summary = parse_pytest_output("tests/foo.py PASSED", "", 0)
        assert summary.framework == "pytest"

    def test_framework_none_when_no_hints(self) -> None:
        summary = parse_pytest_output("all done", "", 0)
        assert summary.framework is None

    def test_returns_test_run_summary_type(self) -> None:
        assert isinstance(parse_pytest_output("1 passed", "", 0), TestRunSummary)

    def test_stderr_also_parsed_for_counts(self) -> None:
        summary = parse_pytest_output("", "3 passed", 0)
        assert summary.passed == 3

    def test_failures_empty_when_all_pass(self) -> None:
        summary = parse_pytest_output("5 passed", "", 0)
        assert summary.failures == []

    def test_only_failed_line_no_summary(self) -> None:
        stdout = "FAILED tests/foo.py::test_bar - RuntimeError: boom\n"
        summary = parse_pytest_output(stdout, "", 1)
        assert len(summary.failures) == 1
        assert summary.failures[0]["test"] == "tests/foo.py::test_bar"
