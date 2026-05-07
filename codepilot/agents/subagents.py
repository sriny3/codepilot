"""Subagent specs for DeepAgents orchestration."""
from __future__ import annotations

from typing import Any

from deepagents import FilesystemPermission  # type: ignore[import]

from codepilot.agents.tools.repo_tools import (
    build_repo_map,
    cache_repo_map,
    load_cached_repo_map,
    retrieve_relevant_files,
)
from codepilot.agents.tools.test_tools import parse_test_output, run_tests

REPO_EXPLORER_PROMPT = """\
You map a repository for a coding task.
1. Call load_cached_repo_map first; if it returns None, call build_repo_map then cache_repo_map.
2. Call retrieve_relevant_files with the issue description.
3. Return structured output: {"repo_map_path": "...", "relevant_files": [...]}
"""

CODER_PROMPT = """\
You implement code changes in the sandbox.
1. Read relevant files with read_file.
2. Call write_todos to plan before editing.
3. Use edit_file for surgical edits (prefer over full-file rewrites).
4. Run execute as a smoke check after each edit.
5. If tests are needed call task("test_agent", ...).
6. On test failure, revise and retry. Max 3 retries; on 3rd failure surface HITL interrupt.
"""

TEST_AGENT_PROMPT = """\
You run and report test results.
1. Call run_tests with the sandbox path, command, and timeout.
2. Call parse_test_output on the raw output.
3. Return structured {"passed": N, "failed": N, "failures": [...]}.
"""

PR_AGENT_PROMPT = """\
You open a pull request.
Branch name MUST be codepilot/issue-{n}-{slug} (slugify title to kebab-case, max 40 chars).
Commit message format: fix(#{n}): {one-line summary} with bullet body and Closes #{n}.
PR body MUST include: issue summary, approach, files changed, test results, Closes #{n}.
Labels: codepilot-generated, needs-review.
Reviewer: issue reporter login.
On merge conflict response: return {"status": "FAILED", "reason": "merge_conflict"} — do NOT resolve.
"""

REPO_EXPLORER: dict[str, Any] = {
    "name": "repo_explorer",
    "description": "Maps a repository and retrieves files relevant to an issue.",
    "system_prompt": REPO_EXPLORER_PROMPT,
    "tools": [build_repo_map, retrieve_relevant_files, load_cached_repo_map, cache_repo_map],
    "permissions": [
        FilesystemPermission(operations=["read"], paths=["/**"], mode="allow"),
        FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
    ],
}

CODER: dict[str, Any] = {
    "name": "coder",
    "description": "Implements code changes in the sandbox given relevant files and a skill.",
    "system_prompt": CODER_PROMPT,
    "skills": ["/skills/definitions/"],
    "tools": [run_tests],
    "permissions": [
        FilesystemPermission(operations=["write"], paths=["/sandbox/**"], mode="allow"),
        FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
        FilesystemPermission(operations=["read"], paths=["/**"], mode="allow"),
    ],
}

TEST_AGENT: dict[str, Any] = {
    "name": "test_agent",
    "description": "Runs the test suite in the sandbox and reports structured results.",
    "system_prompt": TEST_AGENT_PROMPT,
    "tools": [run_tests, parse_test_output],
    "permissions": [
        FilesystemPermission(operations=["read", "write"], paths=["/sandbox/**"], mode="allow"),
        FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
    ],
}

PR_AGENT: dict[str, Any] = {
    "name": "pr_agent",
    "description": "Creates a branch, commits sandbox changes, and opens a structured PR.",
    "system_prompt": PR_AGENT_PROMPT,
    "tools": [],   # inherits GitHub tools from orchestrator
    "permissions": [
        FilesystemPermission(operations=["read"], paths=["/sandbox/**"], mode="allow"),
    ],
}

ALL_SUBAGENTS: list[dict[str, Any]] = [REPO_EXPLORER, CODER, TEST_AGENT, PR_AGENT]
