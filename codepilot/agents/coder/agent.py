"""CoderAgent — applies LLM-generated edits to the sandbox and records the diff."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from codepilot.agents.coder.edits import EditProvider
from codepilot.memory.state import TaskState, WorkingMemory
from codepilot.observability import get_logger
from codepilot.observability.events import Event
from codepilot.sandbox.diff import generate_sandbox_diff

if TYPE_CHECKING:
    from codepilot.guardrails.files import FileGuard
    from codepilot.sandbox.local import LocalSandbox

_log = get_logger("coder")


class CoderAgent:
    """Stage relevant files, generate edits, apply them, record the diff.

    Transitions WorkingMemory from EXPLORING → IMPLEMENTING (or retries
    IMPLEMENTING → IMPLEMENTING) and populates ``wm.proposed_diff`` with a
    unified diff of all changes made inside the sandbox.
    """

    def __init__(
        self,
        sandbox: "LocalSandbox",
        edit_provider: EditProvider,
        *,
        file_guard: "FileGuard | None" = None,
    ) -> None:
        self._sandbox = sandbox
        self._edit_provider = edit_provider
        self._file_guard = file_guard

    def run(
        self,
        wm: WorkingMemory,
        source_root: Path,
        issue_body: str,
        *,
        skill_prompt: str | None = None,
    ) -> WorkingMemory:
        """Stage files, generate edits, apply them, record diff, return wm.

        Steps:
        1. Transition state → IMPLEMENTING (raises InvalidTransition on bad edge).
        2. ``copy_subset``: stage ``wm.relevant_files`` from source_root.
        3. Read staged file contents; missing files get empty string.
        4. Read repo map from sandbox if present.
        5. Call ``edit_provider.generate_edits(…)``.
        6. Validate each edit path with FileGuard; BLOCK → PermissionError.
        7. Write approved edits to sandbox.
        8. Generate unified diff for all tracked files (relevant ∪ edited).
        9. Store diff in ``wm.proposed_diff``.
        10. Emit ``Event.EDIT_APPLIED`` per written file.
        """
        from codepilot.guardrails.base import Decision
        from codepilot.guardrails.files import FileGuard

        wm.transition(TaskState.IMPLEMENTING)

        # Stage relevant source files into sandbox
        self._sandbox.copy_subset(source_root, wm.relevant_files)

        # Read current file contents (files absent in source → empty string)
        file_contents: dict[str, str] = {}
        for rel in wm.relevant_files:
            try:
                file_contents[rel] = self._sandbox.read_file(rel)
            except FileNotFoundError:
                file_contents[rel] = ""

        # Read repo map text if available
        repo_map_text = ""
        if wm.repo_map_path and self._sandbox.exists(wm.repo_map_path):
            repo_map_text = self._sandbox.read_file(wm.repo_map_path)

        edits = self._edit_provider.generate_edits(
            issue_body=issue_body,
            repo_map=repo_map_text,
            file_contents=file_contents,
            skill_prompt=skill_prompt,
        )

        guard = self._file_guard if self._file_guard is not None else FileGuard()
        edited_paths: list[str] = []

        for edit in edits:
            result = guard.validate_path(edit.path)
            if result.decision is Decision.BLOCK:
                raise PermissionError(
                    f"file guard blocked write to {edit.path!r}: {result.reason}"
                )
            self._sandbox.write_file(edit.path, edit.content)
            edited_paths.append(edit.path)
            _log.info(
                Event.EDIT_APPLIED,
                path=edit.path,
                repo=wm.repo,
                issue_id=wm.issue_id,
            )

        # Diff all tracked files: relevant_files ∪ edited_paths (order-preserving dedup)
        all_tracked = list(dict.fromkeys(list(wm.relevant_files) + edited_paths))
        wm.proposed_diff = generate_sandbox_diff(self._sandbox, source_root, all_tracked)

        return wm
