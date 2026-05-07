"""copy_subset tests: only requested files staged; structure preserved; missing skipped."""
from pathlib import Path

import pytest

from codepilot.sandbox.local import LocalSandbox


@pytest.fixture()
def source(tmp_path: Path) -> Path:
    """A source tree with several files."""
    root = tmp_path / "source"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text("# main", encoding="utf-8")
    (root / "src" / "utils.py").write_text("# utils", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_main.py").write_text("# tests", encoding="utf-8")
    (root / "README.md").write_text("readme", encoding="utf-8")
    (root / "requirements.txt").write_text("requests\n", encoding="utf-8")
    (root / "secrets" / ".env").mkdir(parents=True)  # dir, not file, to be skipped
    return root


@pytest.fixture()
def sandbox(tmp_path: Path) -> LocalSandbox:
    root = tmp_path / "sandbox"
    root.mkdir()
    return LocalSandbox(root)


# ── Only requested files staged ────────────────────────────────────────────────


class TestCopySubsetFiltering:
    def test_only_listed_files_present(
        self, sandbox: LocalSandbox, source: Path
    ) -> None:
        sandbox.copy_subset(source, ["src/main.py", "README.md"])
        assert sandbox.exists("src/main.py")
        assert sandbox.exists("README.md")
        assert not sandbox.exists("src/utils.py")
        assert not sandbox.exists("tests/test_main.py")
        assert not sandbox.exists("requirements.txt")

    def test_unlisted_files_absent(
        self, sandbox: LocalSandbox, source: Path
    ) -> None:
        sandbox.copy_subset(source, ["README.md"])
        assert not sandbox.exists("src/main.py")
        assert not sandbox.exists("requirements.txt")

    def test_all_files_copied_when_all_listed(
        self, sandbox: LocalSandbox, source: Path
    ) -> None:
        files = [
            "src/main.py",
            "src/utils.py",
            "tests/test_main.py",
            "README.md",
            "requirements.txt",
        ]
        sandbox.copy_subset(source, files)
        for f in files:
            assert sandbox.exists(f), f"{f!r} should be present"


# ── Structure preserved ────────────────────────────────────────────────────────


class TestCopySubsetStructure:
    def test_nested_path_preserved(
        self, sandbox: LocalSandbox, source: Path
    ) -> None:
        sandbox.copy_subset(source, ["src/main.py"])
        content = sandbox.read_file("src/main.py")
        assert content == "# main"

    def test_content_identical_to_source(
        self, sandbox: LocalSandbox, source: Path
    ) -> None:
        sandbox.copy_subset(source, ["src/utils.py"])
        assert sandbox.read_file("src/utils.py") == "# utils"

    def test_list_files_shows_staged_files(
        self, sandbox: LocalSandbox, source: Path
    ) -> None:
        sandbox.copy_subset(source, ["src/main.py", "README.md"])
        listed = {str(p) for p in sandbox.list_files()}
        assert "src/main.py" in listed or "src\\main.py" in listed
        assert "README.md" in listed


# ── Missing source files skipped ──────────────────────────────────────────────


class TestCopySubsetMissingFiles:
    def test_missing_file_skipped_silently(
        self, sandbox: LocalSandbox, source: Path
    ) -> None:
        # Does not raise; copies what it can
        sandbox.copy_subset(source, ["nonexistent.py", "README.md"])
        assert sandbox.exists("README.md")
        assert not sandbox.exists("nonexistent.py")

    def test_all_missing_leaves_sandbox_empty(
        self, sandbox: LocalSandbox, source: Path
    ) -> None:
        sandbox.copy_subset(source, ["ghost.py", "phantom.txt"])
        assert sandbox.list_files() == []

    def test_empty_file_list_leaves_sandbox_empty(
        self, sandbox: LocalSandbox, source: Path
    ) -> None:
        sandbox.copy_subset(source, [])
        assert sandbox.list_files() == []


# ── Overwrite on re-copy ───────────────────────────────────────────────────────


class TestCopySubsetOverwrite:
    def test_second_copy_overwrites_first(
        self, sandbox: LocalSandbox, source: Path
    ) -> None:
        sandbox.copy_subset(source, ["README.md"])
        assert sandbox.read_file("README.md") == "readme"
        (source / "README.md").write_text("updated readme", encoding="utf-8")
        sandbox.copy_subset(source, ["README.md"])
        assert sandbox.read_file("README.md") == "updated readme"

    def test_independently_written_file_survives_unrelated_copy(
        self, sandbox: LocalSandbox, source: Path
    ) -> None:
        sandbox.write_file("local_notes.txt", "my notes")
        sandbox.copy_subset(source, ["README.md"])
        # local_notes.txt was not in copy_subset; it stays
        assert sandbox.exists("local_notes.txt")


# ── list_files helper ──────────────────────────────────────────────────────────


class TestListFiles:
    def test_empty_sandbox(self, sandbox: LocalSandbox) -> None:
        assert sandbox.list_files() == []

    def test_returns_relative_paths(self, sandbox: LocalSandbox) -> None:
        sandbox.write_file("a.txt", "a")
        sandbox.write_file("sub/b.txt", "b")
        files = sandbox.list_files()
        # All should be relative (no absolute path prefix)
        for f in files:
            assert not f.is_absolute()

    def test_glob_pattern(self, sandbox: LocalSandbox) -> None:
        sandbox.write_file("a.py", "")
        sandbox.write_file("b.txt", "")
        sandbox.write_file("sub/c.py", "")
        py_files = sandbox.list_files("**/*.py")
        txt_files = sandbox.list_files("**/*.txt")
        assert len(py_files) == 2
        assert len(txt_files) == 1
