"""PRAgent — opens a GitHub PR from a tested sandbox diff."""
from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from codepilot.agents.pr_agent.builder import (
    build_pr_body,
    build_pr_title,
    extract_changed_files,
    format_test_summary,
    make_branch_name,
    make_commit_message,
)
from codepilot.memory.state import TaskState, WorkingMemory
from codepilot.observability import get_logger
from codepilot.observability.events import Event

if TYPE_CHECKING:
    from codepilot.github_io.client import GitHubClient
    from codepilot.sandbox.local import LocalSandbox

_log = get_logger("pr_agent")


class PRAgent:
    """Create a branch, commit sandbox edits, and open a pull request.

    Transitions WorkingMemory from TESTING → PR_OPENED and appends
    ``PR #<n>: <url>`` to ``wm.notes``.
    """

    def __init__(
        self,
        gh_client: "GitHubClient",
        sandbox: "LocalSandbox",
        *,
        branch_prefix: str = "codepilot",
        base_branch: str | None = None,
    ) -> None:
        self._gh = gh_client
        self._sandbox = sandbox
        self._branch_prefix = branch_prefix
        self._base_branch = base_branch

    def run(
        self,
        wm: WorkingMemory,
        issue_title: str,
        *,
        pr_labels: Sequence[str] = (),
        reviewers: Sequence[str] = (),
    ) -> WorkingMemory:
        """Create branch, commit changed files, open PR, record results in wm.

        Steps:
        1. Transition state → PR_OPENED (raises InvalidTransition on bad edge).
        2. ``make_branch_name`` → ``gh_client.create_branch``.
        3. ``extract_changed_files(wm.proposed_diff)`` → read each from sandbox.
        4. ``gh_client.commit_files`` with all changed file contents.
        5. ``build_pr_title`` / ``build_pr_body`` → ``gh_client.open_pr``.
        6. Append ``PR #<n>: <url>`` to ``wm.notes``.
        7. Emit BRANCH_CREATED, COMMIT_CREATED, PR_OPENED events.
        """
        wm.transition(TaskState.PR_OPENED)

        branch_name = make_branch_name(wm.issue_id, prefix=self._branch_prefix)
        branch_ref = self._gh.create_branch(branch_name, base=self._base_branch)
        _log.info(
            Event.BRANCH_CREATED,
            branch_name=branch_ref.name,
            base_sha=branch_ref.base_sha,
            repo=wm.repo,
            issue_id=wm.issue_id,
            trace_id=wm.trace_id,
        )

        changed = extract_changed_files(wm.proposed_diff or "")
        files: dict[str, str] = {}
        for rel in changed:
            try:
                files[rel] = self._sandbox.read_file(rel)
            except FileNotFoundError:
                pass

        commit_msg = make_commit_message(wm.issue_id, issue_title)
        commit_ref = self._gh.commit_files(
            branch=branch_name, files=files, message=commit_msg,
        )
        _log.info(
            Event.COMMIT_CREATED,
            sha=commit_ref.sha,
            files_changed=commit_ref.files_changed,
            repo=wm.repo,
            issue_id=wm.issue_id,
            trace_id=wm.trace_id,
        )

        test_sum = format_test_summary(wm.test_results)
        body = build_pr_body(
            issue_id=wm.issue_id,
            issue_title=issue_title,
            proposed_diff=wm.proposed_diff,
            test_summary=test_sum,
        )
        title = build_pr_title(wm.issue_id, issue_title)
        pr_ref = self._gh.open_pr(
            title=title,
            body=body,
            head=branch_name,
            base=self._base_branch,
            labels=pr_labels,
            reviewers=reviewers,
        )
        _log.info(
            Event.PR_OPENED,
            pr_number=pr_ref.number,
            url=pr_ref.url,
            base=pr_ref.base,
            head=pr_ref.head,
            reviewer=pr_ref.reviewer,
            labels=list(pr_ref.labels),
            repo=wm.repo,
            issue_id=wm.issue_id,
            trace_id=wm.trace_id,
        )

        wm.notes.append(f"PR #{pr_ref.number}: {pr_ref.url}")
        return wm
