"""RepoExplorerAgent integration tests."""
from pathlib import Path

import pytest

from codepilot.agents.repo_explorer.agent import RepoExplorerAgent
from codepilot.memory.state import InvalidTransition, TaskState, WorkingMemory
from codepilot.sandbox.local import LocalSandbox


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "auth.py").write_text("def login(): pass\ndef logout(): pass\n")
    (root / "src" / "user.py").write_text("class User: pass\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_auth.py").write_text("def test_login(): pass\n")
    (root / "README.md").write_text("# My App")
    return root


@pytest.fixture()
def sandbox(tmp_path: Path) -> LocalSandbox:
    return LocalSandbox(tmp_path / "sandbox")


@pytest.fixture()
def wm() -> WorkingMemory:
    return WorkingMemory(issue_id=1, repo="owner/repo", trace_id="trace-1")


# ── RepoExplorerAgent.run ──────────────────────────────────────────────────────


class TestRepoExplorerAgentRun:
    def test_transitions_state_to_exploring(
        self, sandbox: LocalSandbox, repo_root: Path, wm: WorkingMemory
    ) -> None:
        RepoExplorerAgent(sandbox).run(wm, repo_root, "fix login bug")
        assert wm.state == TaskState.EXPLORING

    def test_populates_repo_map_path(
        self, sandbox: LocalSandbox, repo_root: Path, wm: WorkingMemory
    ) -> None:
        RepoExplorerAgent(sandbox).run(wm, repo_root, "fix login")
        assert wm.repo_map_path is not None

    def test_repo_map_file_exists_in_sandbox(
        self, sandbox: LocalSandbox, repo_root: Path, wm: WorkingMemory
    ) -> None:
        RepoExplorerAgent(sandbox).run(wm, repo_root, "fix login")
        assert sandbox.exists(wm.repo_map_path)  # type: ignore[arg-type]

    def test_repo_map_file_has_repo_header(
        self, sandbox: LocalSandbox, repo_root: Path, wm: WorkingMemory
    ) -> None:
        RepoExplorerAgent(sandbox).run(wm, repo_root, "fix login")
        content = sandbox.read_file(wm.repo_map_path)  # type: ignore[arg-type]
        assert "# Repo:" in content

    def test_repo_map_file_contains_py_file(
        self, sandbox: LocalSandbox, repo_root: Path, wm: WorkingMemory
    ) -> None:
        RepoExplorerAgent(sandbox).run(wm, repo_root, "fix login")
        content = sandbox.read_file(wm.repo_map_path)  # type: ignore[arg-type]
        assert "src/auth.py" in content

    def test_populates_relevant_files_list(
        self, sandbox: LocalSandbox, repo_root: Path, wm: WorkingMemory
    ) -> None:
        RepoExplorerAgent(sandbox).run(wm, repo_root, "fix login bug")
        assert len(wm.relevant_files) > 0

    def test_relevant_files_are_strings(
        self, sandbox: LocalSandbox, repo_root: Path, wm: WorkingMemory
    ) -> None:
        RepoExplorerAgent(sandbox).run(wm, repo_root, "fix login bug")
        assert all(isinstance(f, str) for f in wm.relevant_files)

    def test_auth_files_surface_for_login_query(
        self, sandbox: LocalSandbox, repo_root: Path, wm: WorkingMemory
    ) -> None:
        RepoExplorerAgent(sandbox).run(wm, repo_root, "fix login authentication bug")
        assert any("auth" in f for f in wm.relevant_files[:3])

    def test_top_n_files_respected(
        self, sandbox: LocalSandbox, repo_root: Path, wm: WorkingMemory
    ) -> None:
        RepoExplorerAgent(sandbox, top_n_files=2).run(wm, repo_root, "fix login")
        assert len(wm.relevant_files) <= 2

    def test_returns_same_wm_object(
        self, sandbox: LocalSandbox, repo_root: Path, wm: WorkingMemory
    ) -> None:
        result = RepoExplorerAgent(sandbox).run(wm, repo_root, "fix login")
        assert result is wm

    def test_raises_invalid_transition_from_wrong_state(
        self, sandbox: LocalSandbox, repo_root: Path
    ) -> None:
        bad_wm = WorkingMemory(issue_id=2, repo="owner/repo", trace_id="t2")
        bad_wm.transition(TaskState.EXPLORING)
        bad_wm.transition(TaskState.IMPLEMENTING)
        with pytest.raises(InvalidTransition):
            RepoExplorerAgent(sandbox).run(bad_wm, repo_root, "some issue")

    def test_empty_repo_still_writes_map(
        self, sandbox: LocalSandbox, tmp_path: Path, wm: WorkingMemory
    ) -> None:
        empty_root = tmp_path / "empty_repo"
        empty_root.mkdir()
        RepoExplorerAgent(sandbox).run(wm, empty_root, "fix bug")
        assert sandbox.exists(wm.repo_map_path)  # type: ignore[arg-type]

    def test_max_tokens_parameter_passed_through(
        self, sandbox: LocalSandbox, repo_root: Path, wm: WorkingMemory
    ) -> None:
        # Very tight budget → map text is short
        agent = RepoExplorerAgent(sandbox, max_tokens=10)
        agent.run(wm, repo_root, "fix login")
        content = sandbox.read_file(wm.repo_map_path)  # type: ignore[arg-type]
        # Header + at most 1-2 entries — text is short
        assert len(content) < 200
