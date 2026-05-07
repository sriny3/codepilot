"""PyGithub wrapper. Sole boundary for non-LLM GitHub I/O.

Used by the deterministic poller and the PR agent. The LLM-callable surface
(GitHubToolkit) lands in Phase 10 and may delegate here for shared auth.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Protocol

from codepilot.github_io.models import BranchRef, CommitRef, IssueRef, PRRef
from codepilot.github_io.prompts import (
    OP_CREATE_BRANCH,
    OP_OPEN_PR_BASE,
    BaseBranchSelector,
    DefaultBranchSelector,
    resolve_base,
)


class _RepoLike(Protocol):
    def get_issues(self, **kw: Any) -> Iterable[Any]: ...
    def get_issue(self, number: int) -> Any: ...
    def get_branch(self, name: str) -> Any: ...
    def get_branches(self) -> Iterable[Any]: ...
    def create_git_ref(self, ref: str, sha: str) -> Any: ...
    def get_contents(self, path: str, ref: str) -> Any: ...
    def update_file(self, path: str, message: str, content: str,
                    sha: str, branch: str) -> Any: ...
    def create_file(self, path: str, message: str, content: str,
                    branch: str) -> Any: ...
    def create_pull(self, *, title: str, body: str,
                    head: str, base: str) -> Any: ...
    def get_commit(self, sha: str) -> Any: ...
    @property
    def default_branch(self) -> str: ...


class _ClientLike(Protocol):
    def get_repo(self, full_name: str) -> _RepoLike: ...


class GitHubClient:
    """Thin, typed facade over PyGithub.

    `gh` parameter is injected — production wires `Github(token)`, tests pass
    a mock that satisfies `_ClientLike`.
    """

    def __init__(
        self,
        gh: _ClientLike,
        repo_full_name: str,
        *,
        base_selector: BaseBranchSelector | None = None,
    ) -> None:
        self._gh = gh
        self._repo_name = repo_full_name
        self._repo: _RepoLike | None = None
        self._base_selector: BaseBranchSelector = base_selector or DefaultBranchSelector()

    @property
    def repo(self) -> _RepoLike:
        if self._repo is None:
            self._repo = self._gh.get_repo(self._repo_name)
        return self._repo

    # --- Issues ---------------------------------------------------------

    def list_open_issues(
        self,
        *,
        labels: Sequence[str] | None = None,
        exclude_ids: Iterable[int] = (),
    ) -> list[IssueRef]:
        kw: dict[str, Any] = {"state": "open"}
        if labels:
            kw["labels"] = list(labels)
        excluded = set(exclude_ids)
        out: list[IssueRef] = []
        for raw in self.repo.get_issues(**kw):
            # PyGithub returns PRs as issues — skip via attr check.
            if getattr(raw, "pull_request", None) is not None:
                continue
            if raw.number in excluded:
                continue
            out.append(IssueRef.from_pygithub(raw, self._repo_name))
        return out

    def get_issue(self, number: int) -> IssueRef:
        return IssueRef.from_pygithub(self.repo.get_issue(number), self._repo_name)

    # --- Branches & commits --------------------------------------------

    def list_branches(self) -> list[str]:
        return [b.name for b in self.repo.get_branches()]

    def _default_base(self) -> str | None:
        try:
            return self.repo.default_branch
        except Exception:
            return None

    def create_branch(self, name: str, base: str | None = None) -> BranchRef:
        """Create `name` branched from `base`. If `base` is None, asks selector."""
        if base is None:
            base = resolve_base(
                self._base_selector,
                operation=OP_CREATE_BRANCH,
                candidates=self.list_branches(),
                default=self._default_base(),
            )
        base_branch = self.repo.get_branch(base)
        base_sha = base_branch.commit.sha
        self.repo.create_git_ref(ref=f"refs/heads/{name}", sha=base_sha)
        return BranchRef(name=name, base_sha=base_sha, repo=self._repo_name)

    def commit_files(
        self,
        *,
        branch: str,
        files: dict[str, str],
        message: str,
    ) -> CommitRef:
        """Write each `path -> content` on `branch`. Returns last commit SHA."""
        last_sha = ""
        for path, content in files.items():
            try:
                existing = self.repo.get_contents(path, ref=branch)
                resp = self.repo.update_file(
                    path=path, message=message, content=content,
                    sha=existing.sha, branch=branch,
                )
            except Exception:
                resp = self.repo.create_file(
                    path=path, message=message, content=content, branch=branch,
                )
            last_sha = resp["commit"].sha
        return CommitRef(
            sha=last_sha, files_changed=len(files),
            branch=branch, repo=self._repo_name,
        )

    # --- PRs -----------------------------------------------------------

    def open_pr(
        self,
        *,
        title: str,
        body: str,
        head: str,
        base: str | None = None,
        labels: Sequence[str] = (),
        reviewers: Sequence[str] = (),
    ) -> PRRef:
        if base is None:
            base = resolve_base(
                self._base_selector,
                operation=OP_OPEN_PR_BASE,
                candidates=self.list_branches(),
                default=self._default_base(),
            )
        pr = self.repo.create_pull(title=title, body=body, head=head, base=base)
        if labels:
            pr.add_to_labels(*labels)
        if reviewers:
            try:
                pr.create_review_request(reviewers=list(reviewers))
            except Exception:
                pass
        return PRRef(
            number=pr.number,
            url=pr.html_url,
            base=base,
            head=head,
            title=title,
            labels=tuple(labels),
            reviewer=(reviewers[0] if reviewers else None),
        )


def build_default_client(
    token: str,
    repo_full_name: str,
    *,
    base_selector: BaseBranchSelector | None = None,
) -> GitHubClient:
    """Production wiring. Imported lazily so unit tests don't need PyGithub."""
    from github import Github

    from codepilot.github_io.prompts import InteractiveSelector

    return GitHubClient(
        Github(token),
        repo_full_name,
        base_selector=base_selector or InteractiveSelector(),
    )
