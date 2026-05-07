"""Tests for repo_tools — uses mocked RepoMap and git."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from langchain_core.tools import BaseTool


class TestRepoToolsAreLangChainTools:
    def test_build_repo_map_is_tool(self) -> None:
        from codepilot.agents.tools.repo_tools import build_repo_map
        assert isinstance(build_repo_map, BaseTool)

    def test_retrieve_relevant_files_is_tool(self) -> None:
        from codepilot.agents.tools.repo_tools import retrieve_relevant_files
        assert isinstance(retrieve_relevant_files, BaseTool)

    def test_cache_repo_map_is_tool(self) -> None:
        from codepilot.agents.tools.repo_tools import cache_repo_map
        assert isinstance(cache_repo_map, BaseTool)

    def test_load_cached_repo_map_is_tool(self) -> None:
        from codepilot.agents.tools.repo_tools import load_cached_repo_map
        assert isinstance(load_cached_repo_map, BaseTool)


class TestCacheRepoMap:
    def test_cache_writes_and_loads(self, tmp_path: Path) -> None:
        from codepilot.agents.tools.repo_tools import cache_repo_map, load_cached_repo_map

        map_text = "repo map content here"
        with patch("codepilot.agents.tools.repo_tools._git_head_sha", return_value="abc123"):
            cache_repo_map.invoke({"root_path": str(tmp_path), "map_text": map_text})
            result = load_cached_repo_map.invoke({"root_path": str(tmp_path)})

        assert result == map_text

    def test_load_returns_none_when_sha_changed(self, tmp_path: Path) -> None:
        from codepilot.agents.tools.repo_tools import cache_repo_map, load_cached_repo_map

        with patch("codepilot.agents.tools.repo_tools._git_head_sha", return_value="sha1"):
            cache_repo_map.invoke({"root_path": str(tmp_path), "map_text": "old map"})

        with patch("codepilot.agents.tools.repo_tools._git_head_sha", return_value="sha2"):
            result = load_cached_repo_map.invoke({"root_path": str(tmp_path)})

        assert result is None

    def test_load_returns_none_when_no_cache(self, tmp_path: Path) -> None:
        from codepilot.agents.tools.repo_tools import load_cached_repo_map

        result = load_cached_repo_map.invoke({"root_path": str(tmp_path)})
        assert result is None

    def test_cache_creates_codepilot_dir(self, tmp_path: Path) -> None:
        from codepilot.agents.tools.repo_tools import cache_repo_map

        with patch("codepilot.agents.tools.repo_tools._git_head_sha", return_value="abc"):
            cache_repo_map.invoke({"root_path": str(tmp_path), "map_text": "x"})

        assert (tmp_path / ".codepilot" / "repo_map.json").exists()

    def test_cache_file_contains_sha_and_map(self, tmp_path: Path) -> None:
        from codepilot.agents.tools.repo_tools import cache_repo_map

        with patch("codepilot.agents.tools.repo_tools._git_head_sha", return_value="deadbeef"):
            cache_repo_map.invoke({"root_path": str(tmp_path), "map_text": "map content"})

        cache_file = tmp_path / ".codepilot" / "repo_map.json"
        data = json.loads(cache_file.read_text())
        assert data["sha"] == "deadbeef"
        assert data["map"] == "map content"

    def test_cache_succeeds_when_parent_dirs_missing(self, tmp_path: Path) -> None:
        from codepilot.agents.tools.repo_tools import cache_repo_map

        # Use a nested subdir that has never been created
        nested_root = tmp_path / "subdir"
        assert not nested_root.exists()

        with patch("codepilot.agents.tools.repo_tools._git_head_sha", return_value="abc"):
            result = cache_repo_map.invoke({"root_path": str(nested_root), "map_text": "x"})

        assert result is None
        assert (nested_root / ".codepilot" / "repo_map.json").exists()


class TestBuildRepoMap:
    def test_build_repo_map_returns_map_text(self) -> None:
        from codepilot.agents.tools.repo_tools import build_repo_map

        with patch("codepilot.agents.repo_explorer.map.RepoMap") as MockRepoMap:
            mock_instance = MockRepoMap.build.return_value
            mock_instance.to_text.return_value = "mocked map text"

            result = build_repo_map.invoke({"root_path": "/tmp"})

        assert result == "mocked map text"


class TestRetrieveRelevantFilesErrorCase:
    def test_returns_empty_list_on_error(self) -> None:
        from codepilot.agents.tools.repo_tools import retrieve_relevant_files

        with patch("codepilot.agents.repo_explorer.map.RepoMap") as MockRepoMap:
            MockRepoMap.build.side_effect = RuntimeError("boom")

            result = retrieve_relevant_files.invoke(
                {"issue_body": "some issue", "repo_root": "/tmp"}
            )

        assert result == []
