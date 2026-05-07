"""Tests for test_tools."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.tools import BaseTool


class TestTestToolsAreLangChainTools:
    def test_run_tests_is_tool(self) -> None:
        from codepilot.agents.tools.test_tools import run_tests
        assert isinstance(run_tests, BaseTool)

    def test_parse_test_output_is_tool(self) -> None:
        from codepilot.agents.tools.test_tools import parse_test_output
        assert isinstance(parse_test_output, BaseTool)


class TestRunTests:
    def test_returns_dict_with_expected_keys(self) -> None:
        from codepilot.agents.tools.test_tools import run_tests

        mock_result = MagicMock()
        mock_result.passed = 5
        mock_result.failed = 0
        mock_result.failures = []

        with patch("codepilot.agents.tools.test_tools._run_suite", return_value=mock_result):
            result = run_tests.invoke(
                {"sandbox_path": "/sandbox", "command": "pytest", "timeout": 30.0}
            )

        assert "passed" in result
        assert "failed" in result
        assert "failures" in result
        assert result["passed"] == 5

    def test_parse_test_output_returns_dict(self) -> None:
        from codepilot.agents.tools.test_tools import parse_test_output

        raw = "PASSED tests/test_foo.py::test_bar\n1 passed in 0.1s"
        result = parse_test_output.invoke({"raw_output": raw, "framework": "pytest"})
        assert isinstance(result, dict)
        assert "passed" in result
