"""Full pipeline integration tests.

Wires all real agents together with fake LLM and fake GitHub so no
external services are needed. Exercises the complete state machine:
TRIAGED → EXPLORING → IMPLEMENTING → TESTING → PR_OPENED → DONE.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from codepilot.agents.coder.agent import CoderAgent
from codepilot.agents.coder.edits import FakeEditProvider, FileEdit
from codepilot.agents.pr_agent.agent import PRAgent
from codepilot.agents.repo_explorer.agent import RepoExplorerAgent
from codepilot.agents.test_agent.agent import TestAgent
from codepilot.agents.test_agent.runner import FakeTestRunner, RunConfig
from codepilot.github_io.client import GitHubClient
from codepilot.github_io.models import IssueRef
from codepilot.memory.state import TaskState, TestRunSummary, WorkingMemory
from codepilot.orchestrator.orchestrator import Orchestrator
from codepilot.sandbox.local import LocalSandbox
from tests.unit._gh_fakes import FakeGitHub, FakeRepo

# ── Shared issue fixture ───────────────────────────────────────────────────────

_ISSUE = IssueRef(
    number=99,
    title="fix add function",
    body="The add function returns wrong result — it subtracts instead of adds.",
    labels=(),
    assignees=(),
    reporter="alice",
    repo="acme/calc",
    state="open",
    created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    url="https://github.com/acme/calc/issues/99",
)

_FIXED_CONTENT = "def add(a, b):\n    return a + b\n"
_BROKEN_CONTENT = "def add(a, b):\n    return a - b  # bug\n"


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture()
def source_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "__init__.py").write_text("")
    (root / "src" / "calculator.py").write_text(_BROKEN_CONTENT)
    (root / "tests" / "__init__.py").write_text("")
    (root / "tests" / "test_calc.py").write_text(
        "import sys, pathlib\n"
        "sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))\n"
        "from src.calculator import add\n\n"
        "def test_add():\n    assert add(1, 2) == 3\n"
    )
    return root


@pytest.fixture()
def sandbox(tmp_path: Path) -> LocalSandbox:
    return LocalSandbox(tmp_path / "sandbox")


@pytest.fixture()
def gh_repo() -> FakeRepo:
    return FakeRepo()


@pytest.fixture()
def gh_client(gh_repo: FakeRepo) -> GitHubClient:
    return GitHubClient(FakeGitHub(gh_repo), "acme/calc")


@pytest.fixture()
def edit_provider() -> FakeEditProvider:
    return FakeEditProvider([FileEdit("src/calculator.py", _FIXED_CONTENT)])


@pytest.fixture()
def pass_runner() -> FakeTestRunner:
    return FakeTestRunner(stdout="1 passed in 0.1s\npytest", exit_code=0)


def _make_orchestrator(
    sandbox: LocalSandbox,
    source_root: Path,
    gh_client: GitHubClient,
    edit_provider: FakeEditProvider,
    runner: FakeTestRunner,
    *,
    max_retries: int = 3,
) -> Orchestrator:
    return Orchestrator(
        RepoExplorerAgent(sandbox),
        CoderAgent(sandbox, edit_provider),
        TestAgent(sandbox, source_root, runner=runner),
        PRAgent(gh_client, sandbox),
        max_retries=max_retries,
        run_config=RunConfig(command="pytest"),
    )


@pytest.fixture()
def wm() -> WorkingMemory:
    return WorkingMemory(issue_id=99, repo="acme/calc", trace_id="e2e-1")


@pytest.fixture()
def done_wm(
    sandbox: LocalSandbox,
    source_root: Path,
    gh_client: GitHubClient,
    edit_provider: FakeEditProvider,
    pass_runner: FakeTestRunner,
    wm: WorkingMemory,
) -> WorkingMemory:
    """Run the happy-path pipeline and return the resulting wm."""
    orch = _make_orchestrator(sandbox, source_root, gh_client, edit_provider, pass_runner)
    return orch.run_issue(wm, _ISSUE, source_root=source_root)


# ── Happy path ─────────────────────────────────────────────────────────────────


class TestHappyPath:
    def test_state_is_done(self, done_wm: WorkingMemory) -> None:
        assert done_wm.state == TaskState.DONE

    def test_relevant_files_populated(self, done_wm: WorkingMemory) -> None:
        assert len(done_wm.relevant_files) > 0

    def test_repo_map_written_to_sandbox(
        self, done_wm: WorkingMemory, sandbox: LocalSandbox
    ) -> None:
        assert sandbox.exists("repo_map.txt")

    def test_proposed_diff_set(self, done_wm: WorkingMemory) -> None:
        assert done_wm.proposed_diff is not None
        assert len(done_wm.proposed_diff) > 0

    def test_test_results_populated(self, done_wm: WorkingMemory) -> None:
        assert done_wm.test_results is not None
        assert done_wm.test_results.passed == 1
        assert done_wm.test_results.failed == 0

    def test_pr_note_in_wm(self, done_wm: WorkingMemory) -> None:
        assert any("PR #" in note for note in done_wm.notes)

    def test_branch_created_in_github(
        self, done_wm: WorkingMemory, gh_repo: FakeRepo
    ) -> None:
        assert len(gh_repo.created_refs) == 1

    def test_files_committed_to_github(
        self, done_wm: WorkingMemory, gh_repo: FakeRepo
    ) -> None:
        all_files = gh_repo.updated_files + gh_repo.created_files
        committed_paths = [r["path"] for r in all_files]
        assert "src/calculator.py" in committed_paths

    def test_edit_applied_to_sandbox(
        self, done_wm: WorkingMemory, sandbox: LocalSandbox
    ) -> None:
        content = sandbox.read_file("src/calculator.py")
        assert "return a + b" in content

    def test_edit_provider_received_issue_body(
        self, done_wm: WorkingMemory, edit_provider: FakeEditProvider
    ) -> None:
        assert edit_provider.last_issue_body == _ISSUE.body

    def test_retry_count_zero_on_clean_run(self, done_wm: WorkingMemory) -> None:
        assert done_wm.retry_count == 0


# ── Retry loop ─────────────────────────────────────────────────────────────────


class TestRetryLoop:
    def test_retry_recovers_to_done(
        self,
        sandbox: LocalSandbox,
        source_root: Path,
        gh_client: GitHubClient,
        edit_provider: FakeEditProvider,
        wm: WorkingMemory,
    ) -> None:
        fail = FakeTestRunner(stdout="1 failed in 0.2s", exit_code=1)
        ok = FakeTestRunner(stdout="1 passed in 0.1s", exit_code=0)

        class _TwoPhaseRunner:
            __test__ = False

            def __init__(self) -> None:
                self._calls = 0

            def run(self, sb: object, *, command: str, timeout: float) -> object:
                self._calls += 1
                if self._calls == 1:
                    return fail.run(sb, command=command, timeout=timeout)
                return ok.run(sb, command=command, timeout=timeout)

        runner = _TwoPhaseRunner()
        orch = _make_orchestrator(sandbox, source_root, gh_client, edit_provider, runner)  # type: ignore[arg-type]
        result = orch.run_issue(wm, _ISSUE, source_root=source_root)
        assert result.state == TaskState.DONE
        assert result.retry_count == 1

    def test_exhausted_retries_marks_failed(
        self,
        sandbox: LocalSandbox,
        source_root: Path,
        gh_client: GitHubClient,
        edit_provider: FakeEditProvider,
        wm: WorkingMemory,
    ) -> None:
        always_fail = FakeTestRunner(stdout="1 failed in 0.2s", exit_code=1)
        orch = _make_orchestrator(
            sandbox, source_root, gh_client, edit_provider, always_fail, max_retries=2
        )
        result = orch.run_issue(wm, _ISSUE, source_root=source_root)
        assert result.state == TaskState.FAILED

    def test_pr_not_opened_after_exhausted_retries(
        self,
        sandbox: LocalSandbox,
        source_root: Path,
        gh_client: GitHubClient,
        edit_provider: FakeEditProvider,
        wm: WorkingMemory,
        gh_repo: FakeRepo,
    ) -> None:
        always_fail = FakeTestRunner(stdout="1 failed in 0.2s", exit_code=1)
        orch = _make_orchestrator(
            sandbox, source_root, gh_client, edit_provider, always_fail, max_retries=1
        )
        orch.run_issue(wm, _ISSUE, source_root=source_root)
        assert len(gh_repo.created_prs) == 0
