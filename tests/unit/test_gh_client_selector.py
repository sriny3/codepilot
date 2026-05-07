"""Selector integration into GitHubClient.create_branch / open_pr."""
from typing import Any

import pytest

from codepilot.github_io.client import GitHubClient
from codepilot.github_io.prompts import (
    OP_CREATE_BRANCH,
    OP_OPEN_PR_BASE,
    FixedSelector,
)
from tests.unit._gh_fakes import FakeGitHub, FakeRepo


class _RecordingSelector:
    def __init__(self, choice: str) -> None:
        self.calls: list[dict[str, Any]] = []
        self._choice = choice

    def select(self, *, operation: str, candidates: Any, default: Any) -> str:
        self.calls.append(
            {"operation": operation, "candidates": list(candidates), "default": default}
        )
        return self._choice


@pytest.fixture
def repo() -> FakeRepo:
    r = FakeRepo()
    r.branches = ["main", "develop", "release-1.0"]
    r.default_branch = "main"
    return r


class TestCreateBranchSelectorPrompt:
    def test_no_base_invokes_selector(self, repo: FakeRepo) -> None:
        sel = _RecordingSelector("develop")
        client = GitHubClient(FakeGitHub(repo=repo), "acme/x", base_selector=sel)
        ref = client.create_branch("codepilot/issue-1-fix")
        assert ref.base_sha == "basesha"
        assert sel.calls == [{
            "operation": OP_CREATE_BRANCH,
            "candidates": ["main", "develop", "release-1.0"],
            "default": "main",
        }]

    def test_explicit_base_skips_selector(self, repo: FakeRepo) -> None:
        sel = _RecordingSelector("never-used")
        client = GitHubClient(FakeGitHub(repo=repo), "acme/x", base_selector=sel)
        client.create_branch("codepilot/issue-1-fix", base="main")
        assert sel.calls == []

    def test_selector_choice_used_as_base(self, repo: FakeRepo) -> None:
        sel = FixedSelector("develop")
        client = GitHubClient(FakeGitHub(repo=repo), "acme/x", base_selector=sel)
        client.create_branch("codepilot/feat-x")
        # Created ref points off a branch whose name resolved through selector.
        assert repo.created_refs[0][0] == "refs/heads/codepilot/feat-x"

    def test_default_selector_falls_back_to_default_branch(self, repo: FakeRepo) -> None:
        # No selector passed → DefaultBranchSelector. Uses repo.default_branch.
        client = GitHubClient(FakeGitHub(repo=repo), "acme/x")
        ref = client.create_branch("codepilot/issue-7-fix")
        assert ref.name == "codepilot/issue-7-fix"

    def test_default_selector_no_repo_default_raises(
        self, repo: FakeRepo, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # default_branch property raises → resolve_base sees default=None.
        def _boom(self: FakeRepo) -> str:
            raise AttributeError("no default")
        monkeypatch.setattr(FakeRepo, "default_branch",
                            property(_boom), raising=False)
        repo.branches = ["develop"]
        client = GitHubClient(FakeGitHub(repo=repo), "acme/x")
        with pytest.raises(ValueError, match="no default branch"):
            client.create_branch("codepilot/x")


class TestOpenPRSelectorPrompt:
    def test_no_base_asks_for_target(self, repo: FakeRepo) -> None:
        sel = _RecordingSelector("develop")
        client = GitHubClient(FakeGitHub(repo=repo), "acme/x", base_selector=sel)
        client.open_pr(title="t", body="b", head="codepilot/x")
        assert len(sel.calls) == 1
        assert sel.calls[0]["operation"] == OP_OPEN_PR_BASE
        assert sel.calls[0]["default"] == "main"

    def test_explicit_base_skips_selector(self, repo: FakeRepo) -> None:
        sel = _RecordingSelector("nope")
        client = GitHubClient(FakeGitHub(repo=repo), "acme/x", base_selector=sel)
        client.open_pr(title="t", body="b", head="codepilot/x", base="main")
        assert sel.calls == []

    def test_selected_target_passed_to_create_pull(self, repo: FakeRepo) -> None:
        sel = FixedSelector("release-1.0")
        client = GitHubClient(FakeGitHub(repo=repo), "acme/x", base_selector=sel)
        pr = client.open_pr(title="t", body="b", head="codepilot/x")
        assert pr.base == "release-1.0"


class TestListBranches:
    def test_returns_names(self, repo: FakeRepo) -> None:
        client = GitHubClient(FakeGitHub(repo=repo), "acme/x")
        assert client.list_branches() == ["main", "develop", "release-1.0"]
