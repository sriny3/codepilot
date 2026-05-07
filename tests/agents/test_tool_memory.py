"""Tests for memory_tools."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.tools import BaseTool


class TestMemoryToolsAreLangChainTools:
    def test_query_lessons_is_tool(self) -> None:
        from codepilot.agents.tools.memory_tools import query_lessons
        assert isinstance(query_lessons, BaseTool)

    def test_add_lesson_is_tool(self) -> None:
        from codepilot.agents.tools.memory_tools import add_lesson
        assert isinstance(add_lesson, BaseTool)


class TestQueryLessons:
    def test_returns_list(self) -> None:
        from codepilot.agents.tools.memory_tools import query_lessons
        from codepilot.memory.episodic import TaskOutcome

        mock_store = MagicMock()
        mock_store.task_records.return_value = [
            TaskOutcome(
                issue_id=1,
                repo="acme/widgets",
                task_type="bug_fix",
                files_modified=["a.py"],
                outcome="passed",
                note="used TDD",
            )
        ]

        with patch("codepilot.agents.tools.memory_tools._get_store", return_value=mock_store):
            result = query_lessons.invoke(
                {"task_description": "fix auth bug", "repo": "acme/widgets", "top_k": 3}
            )

        assert isinstance(result, list)

    def test_add_lesson_calls_store(self) -> None:
        from codepilot.agents.tools.memory_tools import add_lesson

        mock_store = MagicMock()
        with patch("codepilot.agents.tools.memory_tools._get_store", return_value=mock_store):
            add_lesson.invoke(
                {
                    "repo": "acme/widgets",
                    "issue_type": "bug_fix",
                    "files": ["src/auth.py"],
                    "approach": "patched null check",
                    "outcome": "tests passed",
                }
            )

        mock_store.record_task.assert_called_once()
