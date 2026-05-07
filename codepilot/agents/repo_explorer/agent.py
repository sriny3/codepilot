"""RepoExplorerAgent — maps the repo and identifies relevant files for an issue."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from codepilot.agents.repo_explorer.map import RepoMap
from codepilot.agents.repo_explorer.scorer import score_files
from codepilot.memory.state import TaskState, WorkingMemory
from codepilot.observability import get_logger
from codepilot.observability.events import Event

if TYPE_CHECKING:
    from codepilot.sandbox.local import LocalSandbox

_log = get_logger("repo_explorer")

_MAP_FILENAME = "repo_map.txt"


class RepoExplorerAgent:
    """Build a repo map and identify files relevant to a given issue.

    Transitions WorkingMemory from TRIAGED → EXPLORING and populates:
    - ``wm.repo_map_path`` — sandbox-relative path to the saved map text
    - ``wm.relevant_files`` — ordered list of paths most likely to need editing
    """

    def __init__(
        self,
        sandbox: "LocalSandbox",
        *,
        max_tokens: int = 4000,
        top_n_files: int = 20,
    ) -> None:
        self._sandbox = sandbox
        self._max_tokens = max_tokens
        self._top_n = top_n_files

    def run(
        self,
        wm: WorkingMemory,
        repo_root: Path,
        issue_body: str,
    ) -> WorkingMemory:
        """Explore `repo_root`, update `wm`, return `wm`.

        Steps:
        1. Transition state TRIAGED → EXPLORING.
        2. Build a token-budget-aware repo map.
        3. Score entries against the issue body.
        4. Write map text into the sandbox as ``repo_map.txt``.
        5. Populate ``wm.repo_map_path`` and ``wm.relevant_files``.
        6. Emit REPO_MAP_BUILT and FILES_RETRIEVED log events.
        """
        wm.transition(TaskState.EXPLORING)

        repo_map = RepoMap.build(repo_root, max_tokens=self._max_tokens)
        relevant = score_files(repo_map.entries, query=issue_body, top_n=self._top_n)

        map_text = repo_map.to_text()
        self._sandbox.write_file(_MAP_FILENAME, map_text)
        wm.repo_map_path = _MAP_FILENAME
        wm.relevant_files = relevant

        _log.info(
            Event.REPO_MAP_BUILT,
            repo=wm.repo,
            issue_id=wm.issue_id,
            entries=len(repo_map.entries),
            token_estimate=repo_map.token_estimate(),
        )
        _log.info(
            Event.FILES_RETRIEVED,
            repo=wm.repo,
            issue_id=wm.issue_id,
            files=relevant,
            count=len(relevant),
        )

        return wm
