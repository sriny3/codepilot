import pytest

from codepilot.github_io.client import GitHubClient
from codepilot.github_io.models import BranchRef, CommitRef, PRRef
from tests.unit._gh_fakes import (
    FakeGitHub,
    FakeIssue,
    FakeLabel,
    FakeRepo,
    FakeUser,
)


@pytest.fixture
def repo() -> FakeRepo:
    r = FakeRepo()
    r.issues = [
        FakeIssue(number=1, title="A", labels=[FakeLabel("bug")],
                  user=FakeUser("alice")),
        FakeIssue(number=2, title="B", labels=[FakeLabel("ai-assignable")],
                  user=FakeUser("bob")),
        FakeIssue(number=3, title="C", state="closed",
                  user=FakeUser("carol")),
    ]
    return r


@pytest.fixture
def gh(repo: FakeRepo) -> FakeGitHub:
    return FakeGitHub(repo=repo)


@pytest.fixture
def client(gh: FakeGitHub) -> GitHubClient:
    return GitHubClient(gh, "acme/x")


class TestRepoLazyLoad:
    def test_repo_fetched_once(self, gh: FakeGitHub, client: GitHubClient) -> None:
        _ = client.repo
        _ = client.repo
        assert gh.requested_repos == ["acme/x"]


class TestListIssues:
    def test_returns_open_only(self, client: GitHubClient) -> None:
        issues = client.list_open_issues()
        assert {i.number for i in issues} == {1, 2}

    def test_label_filter(self, client: GitHubClient) -> None:
        issues = client.list_open_issues(labels=["ai-assignable"])
        assert {i.number for i in issues} == {2}

    def test_excludes_in_progress(self, client: GitHubClient) -> None:
        issues = client.list_open_issues(exclude_ids=[2])
        assert {i.number for i in issues} == {1}

    def test_skips_pull_requests(self, repo: FakeRepo, client: GitHubClient) -> None:
        repo.issues.append(
            FakeIssue(number=99, title="PR-as-issue", pull_request={"url": "x"},
                      user=FakeUser("bob"))
        )
        issues = client.list_open_issues()
        assert 99 not in {i.number for i in issues}


class TestBranch:
    def test_create_branch_uses_base_sha(self, repo: FakeRepo,
                                         client: GitHubClient) -> None:
        ref = client.create_branch("codepilot/issue-7-fix", base="main")
        assert isinstance(ref, BranchRef)
        assert ref.base_sha == "basesha"
        assert repo.created_refs == [
            ("refs/heads/codepilot/issue-7-fix", "basesha"),
        ]


class TestCommitFiles:
    def test_creates_when_absent(self, repo: FakeRepo, client: GitHubClient) -> None:
        repo._fail_get_contents = True
        ref = client.commit_files(
            branch="b", files={"a.py": "print(1)"}, message="m",
        )
        assert isinstance(ref, CommitRef)
        assert ref.files_changed == 1
        assert repo.created_files[0]["path"] == "a.py"
        assert repo.updated_files == []

    def test_updates_when_present(self, repo: FakeRepo, client: GitHubClient) -> None:
        repo._fail_get_contents = False
        client.commit_files(
            branch="b", files={"a.py": "print(2)"}, message="m",
        )
        assert repo.updated_files[0]["path"] == "a.py"
        assert repo.created_files == []

    def test_multi_file(self, repo: FakeRepo, client: GitHubClient) -> None:
        repo._fail_get_contents = False
        ref = client.commit_files(
            branch="b", files={"a.py": "1", "b.py": "2", "c.py": "3"}, message="m",
        )
        assert ref.files_changed == 3
        assert {u["path"] for u in repo.updated_files} == {"a.py", "b.py", "c.py"}


class TestOpenPR:
    def test_basic_open(self, repo: FakeRepo, client: GitHubClient) -> None:
        pr = client.open_pr(
            title="[CodePilot] fix #1", body="b",
            head="codepilot/issue-1-fix", base="main",
            labels=["codepilot-generated", "needs-review"],
            reviewers=["alice"],
        )
        assert isinstance(pr, PRRef)
        assert pr.number == 1
        assert pr.base == "main"
        assert pr.head == "codepilot/issue-1-fix"
        assert pr.reviewer == "alice"
        assert "codepilot-generated" in pr.labels
        assert repo.last_pr is not None
        assert repo.last_pr._labels == ["codepilot-generated", "needs-review"]
        assert repo.last_pr._reviewers == ["alice"]

    def test_review_failure_swallowed(self, repo: FakeRepo,
                                      client: GitHubClient,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
        original = repo.create_pull

        def patched(**kw):
            pr = original(**kw)
            def boom(*a, **kw):
                raise RuntimeError("api down")
            pr.create_review_request = boom  # type: ignore[method-assign]
            return pr

        monkeypatch.setattr(repo, "create_pull", patched)
        pr = client.open_pr(
            title="t", body="b", head="h", base="main",
            reviewers=["alice"],
        )
        assert pr.number == 1  # reviewer failure does not abort PR
