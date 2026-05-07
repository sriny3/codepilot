"""RepoMap building and text-rendering tests."""
from pathlib import Path

import pytest

from codepilot.agents.repo_explorer.map import RepoMap, RepoMapEntry, _extract_symbols


# ── _extract_symbols ───────────────────────────────────────────────────────────


class TestExtractSymbols:
    def test_extracts_top_level_functions(self, tmp_path: Path) -> None:
        f = tmp_path / "mod.py"
        f.write_text("def foo(): pass\ndef bar(): pass\n")
        assert _extract_symbols(f) == ["foo", "bar"]

    def test_extracts_classes(self, tmp_path: Path) -> None:
        f = tmp_path / "mod.py"
        f.write_text("class Foo: pass\nclass Bar: pass\n")
        assert _extract_symbols(f) == ["Foo", "Bar"]

    def test_async_functions_extracted(self, tmp_path: Path) -> None:
        f = tmp_path / "mod.py"
        f.write_text("async def run(): pass\n")
        assert "run" in _extract_symbols(f)

    def test_nested_not_extracted(self, tmp_path: Path) -> None:
        f = tmp_path / "mod.py"
        f.write_text("class Outer:\n    def inner(self): pass\n")
        symbols = _extract_symbols(f)
        assert "Outer" in symbols
        assert "inner" not in symbols

    def test_syntax_error_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.py"
        f.write_bytes(b"def foo( INVALID SYNTAX !!!!")
        assert _extract_symbols(f) == []

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.py"
        f.write_text("")
        assert _extract_symbols(f) == []

    def test_mixed_class_and_function(self, tmp_path: Path) -> None:
        f = tmp_path / "mod.py"
        f.write_text("class Alpha: pass\ndef beta(): pass\nclass Gamma: pass\n")
        symbols = _extract_symbols(f)
        assert symbols == ["Alpha", "beta", "Gamma"]


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text("def main(): pass\nclass App: pass\n")
    (root / "src" / "utils.py").write_text("def helper(): pass\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_main.py").write_text("def test_app(): pass\n")
    (root / "README.md").write_text("# readme")
    (root / "requirements.txt").write_text("requests\n")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "cached.pyc").write_bytes(b"")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main")
    return root


# ── RepoMap.build ──────────────────────────────────────────────────────────────


class TestRepoMapBuild:
    def test_py_files_included(self, repo_root: Path) -> None:
        rm = RepoMap.build(repo_root)
        paths = {e.path for e in rm.entries}
        assert "src/main.py" in paths
        assert "src/utils.py" in paths
        assert "tests/test_main.py" in paths

    def test_non_py_files_included(self, repo_root: Path) -> None:
        rm = RepoMap.build(repo_root)
        paths = {e.path for e in rm.entries}
        assert "README.md" in paths
        assert "requirements.txt" in paths

    def test_pycache_excluded(self, repo_root: Path) -> None:
        rm = RepoMap.build(repo_root)
        paths = {e.path for e in rm.entries}
        assert not any("__pycache__" in p for p in paths)

    def test_git_dir_excluded(self, repo_root: Path) -> None:
        rm = RepoMap.build(repo_root)
        paths = {e.path for e in rm.entries}
        assert not any(".git" in p for p in paths)

    def test_symbols_extracted_for_py_files(self, repo_root: Path) -> None:
        rm = RepoMap.build(repo_root)
        main_entry = next(e for e in rm.entries if e.path == "src/main.py")
        assert "main" in main_entry.symbols
        assert "App" in main_entry.symbols

    def test_non_py_has_no_symbols(self, repo_root: Path) -> None:
        rm = RepoMap.build(repo_root)
        readme = next(e for e in rm.entries if e.path == "README.md")
        assert readme.symbols == ()

    def test_entries_sorted_by_path(self, repo_root: Path) -> None:
        rm = RepoMap.build(repo_root)
        paths = [e.path for e in rm.entries]
        assert paths == sorted(paths)

    def test_empty_dir_returns_empty_entries(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty_repo"
        empty.mkdir()
        rm = RepoMap.build(empty)
        assert rm.entries == []

    def test_repo_root_stored(self, repo_root: Path) -> None:
        rm = RepoMap.build(repo_root)
        assert rm.repo_root == repo_root.resolve()

    def test_token_budget_limits_entries(self, repo_root: Path) -> None:
        full = RepoMap.build(repo_root)
        small = RepoMap.build(repo_root, max_tokens=10)
        assert len(small.entries) < len(full.entries)

    def test_at_least_one_entry_despite_tight_budget(self, repo_root: Path) -> None:
        rm = RepoMap.build(repo_root, max_tokens=1)
        assert len(rm.entries) >= 1

    def test_size_bytes_populated(self, repo_root: Path) -> None:
        rm = RepoMap.build(repo_root)
        main_entry = next(e for e in rm.entries if e.path == "src/main.py")
        assert main_entry.size_bytes > 0


# ── RepoMap.to_text / token_estimate / save ────────────────────────────────────


class TestRepoMapText:
    def test_header_contains_repo_name(self, repo_root: Path) -> None:
        rm = RepoMap.build(repo_root)
        assert repo_root.name in rm.to_text()

    def test_file_paths_in_text(self, repo_root: Path) -> None:
        rm = RepoMap.build(repo_root)
        assert "src/main.py" in rm.to_text()

    def test_symbols_appear_in_text(self, repo_root: Path) -> None:
        rm = RepoMap.build(repo_root)
        text = rm.to_text()
        assert "main" in text
        assert "App" in text

    def test_token_estimate_positive(self, repo_root: Path) -> None:
        rm = RepoMap.build(repo_root)
        assert rm.token_estimate() > 0

    def test_empty_map_has_header_line(self, tmp_path: Path) -> None:
        empty_root = tmp_path / "empty"
        empty_root.mkdir()
        rm = RepoMap.build(empty_root)
        assert "# Repo:" in rm.to_text()

    def test_save_writes_file(self, tmp_path: Path, repo_root: Path) -> None:
        rm = RepoMap.build(repo_root)
        out = tmp_path / "map.txt"
        rm.save(out)
        assert out.exists()
        assert repo_root.name in out.read_text()

    def test_save_creates_parent_dirs(self, tmp_path: Path, repo_root: Path) -> None:
        rm = RepoMap.build(repo_root)
        out = tmp_path / "nested" / "deep" / "map.txt"
        rm.save(out)
        assert out.exists()

    def test_entry_without_symbols_has_no_brackets(self, tmp_path: Path) -> None:
        root = tmp_path / "r"
        root.mkdir()
        (root / "notes.md").write_text("hi")
        rm = RepoMap.build(root)
        text = rm.to_text()
        assert "[" not in text
