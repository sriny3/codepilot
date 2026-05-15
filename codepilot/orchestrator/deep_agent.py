"""DeepAgents orchestrator — replaces orchestrator.py."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from deepagents import FilesystemPermission, create_deep_agent  # type: ignore[import]
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from codepilot.agents.subagents import ALL_SUBAGENTS
from codepilot.agents.tools.github_tools import (
    get_issue,
    list_open_issues,
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
You are an autonomous coding agent. Each task message ends with "Workspace: <path>".
Extract that path and pass it verbatim as workspace_path in every subagent task description.
IMPORTANT: The workspace path uses forward slashes (e.g. ".codepilot/workspace/financebot").
Use it EXACTLY as given — do NOT add a leading "/" or convert to any other format.

AUTONOMY RULES — strictly required:
- NEVER ask the user for clarification. Always make a best-effort judgment and proceed.
- NEVER stop to report status or ask for next steps. Keep going until the pipeline is done or failed.
- If the issue is vague (e.g. "documentation needs update"), infer the most impactful changes from the repo map and proceed.
- Only surface a HITL interrupt on: 3rd consecutive test failure, or a merge conflict.

For each GitHub issue:
1. Call classify_issue to determine task type (bug_fix, feature_addition, dependency_update, documentation, config_change).
2. Call query_lessons for top-3 past lessons and include them in context.
3. Call get_issue(issue_number=<n>) to fetch issue title, body, reporter login, and url.
4. Call write_todos to plan the implementation as a checklist.
5. Call task("repo_explorer", description="... workspace_path=<path>") to map the repo and find relevant files.
6. Call task("coder", description="... workspace_path=<path> skill=<skill> relevant_files=<files>").
7. On test failure: retry coder up to 3 times with failure details.
8. Call task("pr_agent", description=<full PR brief>) when tests pass to open the PR. The
   description MUST include all of these as labeled fields:
     issue_number=<n>
     issue_title=<title from get_issue>
     issue_reporter=<reporter from get_issue>
     issue_url=<url from get_issue>
     workspace_path=<path>
     files_modified=<comma-separated paths the coder edited>
     approach_summary=<1-2 sentence summary of what was done>
     test_results=<pass/fail summary from test_agent>
9. Call add_lesson on success with the approach and outcome.

IMPORTANT: Never call ls, read_file, write_file, or execute directly. All filesystem operations go through subagents.
If pr_agent task returns merge_conflict: do NOT retry — report FAILED immediately.
State progression: TRIAGED → EXPLORING → IMPLEMENTING → TESTING → PR_OPENED → DONE | FAILED
"""



def build_orchestrator(cfg: "PipelineConfig") -> Any:  # type: ignore[return]
    """Build and return the DeepAgents CompiledStateGraph orchestrator."""
    return create_deep_agent(
        model="anthropic:claude-haiku-4-5-20251001",
        tools=[
            classify_issue,
            build_repo_map,
            retrieve_relevant_files,
            load_cached_repo_map,
            cache_repo_map,
            query_lessons,
            add_lesson,
            list_open_issues,
            get_issue,

        ],
        subagents=ALL_SUBAGENTS,
        system_prompt=ORCHESTRATOR_PROMPT,
        permissions=[
            FilesystemPermission(operations=["write"], paths=["/sandbox/**"], mode="allow"),
            FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
            FilesystemPermission(operations=["read"], paths=["/**"], mode="allow"),
        ],
        store=InMemoryStore(),
        checkpointer=MemorySaver(),
        memory=[],
    )
