"""DeepAgents orchestrator — replaces orchestrator.py."""
from __future__ import annotations

from typing import TYPE_CHECKING

from deepagents import FilesystemPermission, create_deep_agent  # type: ignore[import]
from langchain_community.agent_toolkits.github.toolkit import GitHubToolkit  # type: ignore[import]
from langchain_community.utilities.github import GitHubAPIWrapper  # type: ignore[import]
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from codepilot.agents.subagents import ALL_SUBAGENTS
from codepilot.agents.tools.github_tools import (
    commit_files,
    create_branch,
    get_issue,
    list_open_issues,
    open_pr,
)
from codepilot.agents.tools.memory_tools import add_lesson, query_lessons
from codepilot.agents.tools.repo_tools import (
    build_repo_map,
    cache_repo_map,
    load_cached_repo_map,
    retrieve_relevant_files,
)
from codepilot.orchestrator.classifier import classify_issue

if TYPE_CHECKING:
    from codepilot.orchestrator.factory import PipelineConfig

ORCHESTRATOR_PROMPT = """\
You are an autonomous coding agent. For each GitHub issue:
1. Call classify_issue to determine task type (bug_fix, feature_addition, dependency_update, documentation, config_change).
2. Call query_lessons for top-3 past lessons and include them in context.
3. Call write_todos to plan the implementation as a checklist.
4. Call task("repo_explorer", ...) to map the repo and find relevant files.
5. Call task("coder", ...) injecting the classified skill name and relevant files.
6. On test failure: retry coder up to 3 times with failure details.
7. Call task("pr_agent", ...) when tests pass to open the PR.
8. Call add_lesson on success with the approach and outcome.

On merge conflict response from commit_files: do NOT retry — report FAILED immediately.
State progression: TRIAGED → EXPLORING → IMPLEMENTING → TESTING → PR_OPENED → DONE | FAILED
"""


def _get_toolkit_tools() -> list:
    """Build GitHubToolkit tools from settings. Returns empty list on failure (e.g. invalid key in tests)."""
    try:
        from codepilot.config.settings import get_settings

        settings = get_settings()
        github_wrapper = GitHubAPIWrapper(
            github_app_id=settings.github_app_id,
            github_app_private_key=settings.github_app_private_key.get_secret_value(),
            github_repository=settings.repo_full_name,
        )
        return GitHubToolkit.from_github_api_wrapper(github_wrapper).get_tools()
    except Exception:
        return []


def build_orchestrator(cfg: "PipelineConfig"):  # type: ignore[return]
    """Build and return the DeepAgents CompiledStateGraph orchestrator."""
    toolkit_tools = _get_toolkit_tools()

    return create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        tools=[
            *toolkit_tools,
            classify_issue,
            build_repo_map,
            retrieve_relevant_files,
            load_cached_repo_map,
            cache_repo_map,
            query_lessons,
            add_lesson,
            list_open_issues,
            get_issue,
            create_branch,
            commit_files,
            open_pr,
        ],
        subagents=ALL_SUBAGENTS,
        system_prompt=ORCHESTRATOR_PROMPT,
        permissions=[
            FilesystemPermission(operations=["write"], paths=["/sandbox/**"], mode="allow"),
            FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
            FilesystemPermission(operations=["read"], paths=["/**"], mode="allow"),
        ],
        interrupt_on={
            "open_pr": True,
            "commit_files": True,
        },
        store=InMemoryStore(),
        checkpointer=MemorySaver(),
        memory=["/memory/AGENTS.md"],
    )
