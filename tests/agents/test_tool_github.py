"""Tests for github_tools — uses mocked GitHubAPIWrapper."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.tools import BaseTool


class TestGithubToolsAreLangChainTools:
    def test_list_open_issues_is_tool(self) -> None:
        from codepilot.agents.tools.github_tools import list_open_issues
        assert isinstance(list_open_issues, BaseTool)

    def test_get_issue_is_tool(self) -> None:
        from codepilot.agents.tools.github_tools import get_issue
        assert isinstance(get_issue, BaseTool)

    def test_create_branch_is_tool(self) -> None:
        from codepilot.agents.tools.github_tools import create_branch
        assert isinstance(create_branch, BaseTool)

    def test_commit_files_is_tool(self) -> None:
        from codepilot.agents.tools.github_tools import commit_files
        assert isinstance(commit_files, BaseTool)

    def test_open_pr_is_tool(self) -> None:
        from codepilot.agents.tools.github_tools import open_pr
        assert isinstance(open_pr, BaseTool)


class TestCommitFilesMergeConflict:
    def test_merge_conflict_returns_error_dict(self, min_env: None) -> None:
        from codepilot.agents.tools.github_tools import commit_files

        mock_wrapper = MagicMock()
        exc = Exception("422: merge conflict detected")

        with patch(
            "codepilot.agents.tools.github_tools._get_wrapper",
            return_value=mock_wrapper,
        ):
            mock_wrapper.create_file.side_effect = exc

            result = commit_files.invoke(
                {
                    "branch": "codepilot/issue-1-fix",
                    "file_paths": ["src/main.py"],
                    "message": "fix(#1): patch",
                }
            )

        assert isinstance(result, dict)
        assert result.get("error") == "merge_conflict"

    def test_normal_commit_returns_string(self, min_env: None) -> None:
        from codepilot.agents.tools.github_tools import commit_files

        mock_wrapper = MagicMock()
        mock_wrapper.create_file.return_value = None

        with patch(
            "codepilot.agents.tools.github_tools._get_wrapper",
            return_value=mock_wrapper,
        ):
            result = commit_files.invoke(
                {
                    "branch": "codepilot/issue-1-fix",
                    "file_paths": ["src/main.py"],
                    "message": "fix(#1): patch",
                }
            )

        assert isinstance(result, str)

    def test_non_conflict_exception_is_reraised(self, min_env: None) -> None:
        from codepilot.agents.tools.github_tools import commit_files

        mock_wrapper = MagicMock()
        mock_wrapper.create_file.side_effect = ConnectionError("network error")

        with patch(
            "codepilot.agents.tools.github_tools._get_wrapper",
            return_value=mock_wrapper,
        ):
            with pytest.raises(ConnectionError):
                commit_files.invoke(
                    {
                        "branch": "codepilot/issue-1-fix",
                        "file_paths": ["src/main.py"],
                        "message": "fix(#1): patch",
                    }
                )
