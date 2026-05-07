"""CoderAgent integration tests."""
from pathlib import Path

import pytest

from codepilot.agents.coder.agent import CoderAgent
from codepilot.agents.coder.edits import FakeEditProvider, FileEdit
from codepilot.guardrails.base import Decision
from codepilot.guardrails.files import FileGuard, FileRule
from codepilot.memory.state import InvalidTransition, TaskState, WorkingMemory
from codepilot.sandbox.local import LocalSandbox


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture()
def source_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "auth.py").write_text("def login(): return False\n")
    (root / "src" / "utils.py").write_text("def helper(): pass\n")
    return root


@pytest.fixture()
def sandbox(tmp_path: Path) -> LocalSandbox:
    return LocalSandbox(tmp_path / "sandbox")


@pytest.fixture()
def wm() -> WorkingMemory:
    w = WorkingMemory(issue_id=1, repo="owner/repo", trace_id="t1")
    w.transition(TaskState.EXPLORING)
    w.relevant_files = ["src/auth.py", "src/utils.py"]
    return w


# ── CoderAgent.run ─────────────────────────────────────────────────────────────


class TestCoderAgentRun:
    def test_transitions_to_implementing(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        CoderAgent(sandbox, FakeEditProvider()).run(wm, source_root, "fix login")
        assert wm.state == TaskState.IMPLEMENTING

    def test_edit_written_to_sandbox(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        edits = [FileEdit("src/auth.py", "def login(): return True\n")]
        CoderAgent(sandbox, FakeEditProvider(edits)).run(wm, source_root, "fix")
        assert sandbox.read_file("src/auth.py") == "def login(): return True\n"

    def test_proposed_diff_populated(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        edits = [FileEdit("src/auth.py", "def login(): return True\n")]
        CoderAgent(sandbox, FakeEditProvider(edits)).run(wm, source_root, "fix")
        assert wm.proposed_diff is not None
        assert len(wm.proposed_diff) > 0

    def test_diff_shows_removed_and_added_line(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        edits = [FileEdit("src/auth.py", "def login(): return True\n")]
        CoderAgent(sandbox, FakeEditProvider(edits)).run(wm, source_root, "fix")
        assert "-def login(): return False" in wm.proposed_diff
        assert "+def login(): return True" in wm.proposed_diff

    def test_no_edits_yields_empty_diff(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        CoderAgent(sandbox, FakeEditProvider([])).run(wm, source_root, "nothing")
        assert wm.proposed_diff == ""

    def test_issue_body_passed_to_provider(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        provider = FakeEditProvider()
        CoderAgent(sandbox, provider).run(wm, source_root, "specific issue body")
        assert provider.last_issue_body == "specific issue body"

    def test_file_contents_passed_to_provider(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        provider = FakeEditProvider()
        CoderAgent(sandbox, provider).run(wm, source_root, "bug")
        assert "src/auth.py" in provider.last_file_contents
        assert "login" in provider.last_file_contents["src/auth.py"]

    def test_skill_prompt_forwarded_to_provider(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        provider = FakeEditProvider()
        CoderAgent(sandbox, provider).run(
            wm, source_root, "bug", skill_prompt="write tests first"
        )
        assert provider.last_skill_prompt == "write tests first"

    def test_skill_prompt_defaults_to_none(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        provider = FakeEditProvider()
        CoderAgent(sandbox, provider).run(wm, source_root, "bug")
        assert provider.last_skill_prompt is None

    def test_new_file_addition_appears_in_diff(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        edits = [FileEdit("src/new_module.py", "# brand new\n")]
        CoderAgent(sandbox, FakeEditProvider(edits)).run(
            wm, source_root, "add new module"
        )
        assert "+# brand new" in wm.proposed_diff

    def test_file_guard_blocks_env_file(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        edits = [FileEdit("secrets.env", "TOKEN=bad\n")]
        with pytest.raises(PermissionError):
            CoderAgent(sandbox, FakeEditProvider(edits)).run(
                wm, source_root, "try to write secrets"
            )

    def test_custom_file_guard_blocks_custom_pattern(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        extra = [FileRule("no_lock", "*.lock", Decision.BLOCK, "no lockfiles")]
        guard = FileGuard(extra_rules=extra)
        edits = [FileEdit("poetry.lock", "lock content")]
        with pytest.raises(PermissionError):
            CoderAgent(sandbox, FakeEditProvider(edits), file_guard=guard).run(
                wm, source_root, "update lock"
            )

    def test_raises_invalid_transition_from_triaged(
        self, sandbox: LocalSandbox, source_root: Path
    ) -> None:
        # TRIAGED → IMPLEMENTING not allowed; must go through EXPLORING
        bad_wm = WorkingMemory(issue_id=2, repo="owner/repo", trace_id="t2")
        with pytest.raises(InvalidTransition):
            CoderAgent(sandbox, FakeEditProvider()).run(bad_wm, source_root, "bug")

    def test_implementing_to_implementing_is_valid_retry(
        self, sandbox: LocalSandbox, source_root: Path
    ) -> None:
        retry_wm = WorkingMemory(issue_id=3, repo="owner/repo", trace_id="t3")
        retry_wm.transition(TaskState.EXPLORING)
        retry_wm.transition(TaskState.IMPLEMENTING)
        retry_wm.relevant_files = ["src/auth.py"]
        edits = [FileEdit("src/auth.py", "def login(): return True\n")]
        CoderAgent(sandbox, FakeEditProvider(edits)).run(
            retry_wm, source_root, "retry fix"
        )
        assert retry_wm.state == TaskState.IMPLEMENTING

    def test_missing_source_file_produces_pure_addition_diff(
        self, sandbox: LocalSandbox, source_root: Path
    ) -> None:
        new_wm = WorkingMemory(issue_id=4, repo="owner/repo", trace_id="t4")
        new_wm.transition(TaskState.EXPLORING)
        new_wm.relevant_files = []
        edits = [FileEdit("src/brand_new.py", "# created by agent\n")]
        CoderAgent(sandbox, FakeEditProvider(edits)).run(
            new_wm, source_root, "add file"
        )
        assert "+# created by agent" in new_wm.proposed_diff

    def test_returns_same_wm_object(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        result = CoderAgent(sandbox, FakeEditProvider()).run(wm, source_root, "bug")
        assert result is wm

    def test_repo_map_text_passed_to_provider(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        sandbox.write_file("repo_map.txt", "# Repo: myapp\n  src/auth.py\n")
        wm.repo_map_path = "repo_map.txt"
        provider = FakeEditProvider()
        CoderAgent(sandbox, provider).run(wm, source_root, "bug")
        assert "# Repo: myapp" in provider.last_repo_map

    def test_empty_repo_map_when_not_set(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        provider = FakeEditProvider()
        CoderAgent(sandbox, provider).run(wm, source_root, "bug")
        assert provider.last_repo_map == ""

    def test_multiple_edits_all_written(
        self, sandbox: LocalSandbox, source_root: Path, wm: WorkingMemory
    ) -> None:
        edits = [
            FileEdit("src/auth.py", "def login(): return True\n"),
            FileEdit("src/utils.py", "def helper(): return 42\n"),
        ]
        CoderAgent(sandbox, FakeEditProvider(edits)).run(wm, source_root, "fix both")
        assert sandbox.read_file("src/auth.py") == "def login(): return True\n"
        assert sandbox.read_file("src/utils.py") == "def helper(): return 42\n"
