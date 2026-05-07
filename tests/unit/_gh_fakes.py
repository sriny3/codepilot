"""Tiny fakes for PyGithub objects. Keep tests offline + deterministic."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class FakeUser:
    login: str


@dataclass
class FakeLabel:
    name: str


@dataclass
class FakeIssue:
    number: int
    title: str = ""
    body: str = ""
    state: str = "open"
    labels: list[FakeLabel] = field(default_factory=list)
    assignees: list[FakeUser] = field(default_factory=list)
    user: FakeUser | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    html_url: str = "https://github.com/acme/x/issues/0"
    pull_request: Any = None  # PyGithub: non-None means it's a PR


@dataclass
class FakeCommit:
    sha: str = "deadbeef"


@dataclass
class FakeBranch:
    name: str = "main"
    commit: FakeCommit = field(default_factory=FakeCommit)


@dataclass
class FakePR:
    number: int = 1
    html_url: str = "https://github.com/acme/x/pull/1"
    title: str = "PR"
    _labels: list[str] = field(default_factory=list)
    _reviewers: list[str] = field(default_factory=list)

    def add_to_labels(self, *names: str) -> None:
        self._labels.extend(names)

    def create_review_request(self, reviewers: list[str]) -> None:
        self._reviewers.extend(reviewers)


@dataclass
class FakeContent:
    sha: str = "fc1"


@dataclass
class FakeUpdateResp:
    commit: FakeCommit


class FakeRepo:
    """Records calls; returns canned objects."""

    def __init__(self) -> None:
        self.issues: list[FakeIssue] = []
        self.created_refs: list[tuple[str, str]] = []
        self.created_files: list[dict[str, Any]] = []
        self.updated_files: list[dict[str, Any]] = []
        self.created_prs: list[FakePR] = []
        self._fail_get_contents: bool = False
        self.last_pr: FakePR | None = None
        self.branches: list[str] = ["main", "develop"]
        self.default_branch: str = "main"

    # -- read APIs --
    def get_issues(self, **kw: Any) -> list[FakeIssue]:
        state = kw.get("state", "open")
        labels = kw.get("labels")
        out = [i for i in self.issues if i.state == state]
        if labels:
            wanted = set(labels)
            out = [i for i in out if wanted.issubset({l.name for l in i.labels})]
        return out

    def get_issue(self, number: int) -> FakeIssue:
        return next(i for i in self.issues if i.number == number)

    def get_branch(self, name: str) -> FakeBranch:
        return FakeBranch(name=name, commit=FakeCommit(sha="basesha"))

    def get_branches(self) -> list[FakeBranch]:
        return [FakeBranch(name=n, commit=FakeCommit(sha=f"sha-{n}"))
                for n in self.branches]

    def get_contents(self, path: str, ref: str) -> FakeContent:
        if self._fail_get_contents:
            raise FileNotFoundError(path)
        return FakeContent()

    def get_commit(self, sha: str) -> FakeCommit:
        return FakeCommit(sha=sha)

    # -- write APIs --
    def create_git_ref(self, ref: str, sha: str) -> dict[str, str]:
        self.created_refs.append((ref, sha))
        return {"ref": ref, "sha": sha}

    def update_file(self, path: str, message: str, content: str,
                    sha: str, branch: str) -> dict[str, Any]:
        rec = {"path": path, "message": message, "content": content,
               "sha": sha, "branch": branch}
        self.updated_files.append(rec)
        return {"commit": FakeCommit(sha=f"upd-{path}")}

    def create_file(self, path: str, message: str, content: str,
                    branch: str) -> dict[str, Any]:
        rec = {"path": path, "message": message, "content": content, "branch": branch}
        self.created_files.append(rec)
        return {"commit": FakeCommit(sha=f"new-{path}")}

    def create_pull(self, *, title: str, body: str,
                    head: str, base: str) -> FakePR:
        n = len(self.created_prs) + 1
        pr = FakePR(number=n, title=title,
                    html_url=f"https://github.com/acme/x/pull/{n}")
        self.created_prs.append(pr)
        self.last_pr = pr
        return pr


class FakeGitHub:
    def __init__(self, repo: FakeRepo | None = None) -> None:
        self._repo = repo or FakeRepo()
        self.requested_repos: list[str] = []

    def get_repo(self, full_name: str) -> FakeRepo:
        self.requested_repos.append(full_name)
        return self._repo
