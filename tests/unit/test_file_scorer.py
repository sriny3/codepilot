"""File relevance scorer tests."""
import pytest

from codepilot.agents.repo_explorer.map import RepoMapEntry
from codepilot.agents.repo_explorer.scorer import _tokenise, score_files


# ── _tokenise ──────────────────────────────────────────────────────────────────


class TestTokenise:
    def test_lowercases_input(self) -> None:
        assert "hello" in _tokenise("HELLO world")

    def test_removes_stop_words(self) -> None:
        assert _tokenise("a the is in it of to") == []

    def test_alphanumeric_only(self) -> None:
        tokens = _tokenise("foo-bar baz_qux")
        assert "foo" in tokens
        assert "bar" in tokens

    def test_single_char_removed(self) -> None:
        assert _tokenise("a b c") == []

    def test_numbers_kept(self) -> None:
        assert "42" in _tokenise("line 42 error")

    def test_empty_string_returns_empty(self) -> None:
        assert _tokenise("") == []


# ── score_files ────────────────────────────────────────────────────────────────


@pytest.fixture()
def entries() -> list[RepoMapEntry]:
    return [
        RepoMapEntry(path="src/auth.py", symbols=("LoginView", "authenticate")),
        RepoMapEntry(path="src/user.py", symbols=("User", "create_user")),
        RepoMapEntry(path="tests/test_auth.py", symbols=("test_login",)),
        RepoMapEntry(path="README.md", symbols=()),
        RepoMapEntry(path="requirements.txt", symbols=()),
    ]


class TestScoreFiles:
    def test_auth_file_ranked_high_for_auth_query(
        self, entries: list[RepoMapEntry]
    ) -> None:
        result = score_files(entries, query="fix authentication login bug")
        assert result[0] in {"src/auth.py", "tests/test_auth.py"}

    def test_returns_top_n(self, entries: list[RepoMapEntry]) -> None:
        result = score_files(entries, query="auth", top_n=2)
        assert len(result) == 2

    def test_returns_all_when_fewer_than_top_n(
        self, entries: list[RepoMapEntry]
    ) -> None:
        result = score_files(entries, query="auth", top_n=100)
        assert len(result) == len(entries)

    def test_empty_query_returns_first_n_in_order(
        self, entries: list[RepoMapEntry]
    ) -> None:
        result = score_files(entries, query="", top_n=3)
        assert len(result) == 3
        assert result == [e.path for e in entries[:3]]

    def test_symbol_match_scores_higher_than_no_match(
        self, entries: list[RepoMapEntry]
    ) -> None:
        result = score_files(entries, query="authenticate user login")
        auth_idx = next(i for i, p in enumerate(result) if "auth.py" in p)
        readme_idx = next(i for i, p in enumerate(result) if "README" in p)
        assert auth_idx < readme_idx

    def test_path_match_boosts_ranking(self, entries: list[RepoMapEntry]) -> None:
        result = score_files(entries, query="user model")
        user_idx = result.index("src/user.py")
        req_idx = result.index("requirements.txt")
        assert user_idx < req_idx

    def test_py_extension_preferred_over_txt(
        self, entries: list[RepoMapEntry]
    ) -> None:
        result = score_files(entries, query="authenticate")
        py_paths = [p for p in result if p.endswith(".py")]
        txt_paths = [p for p in result if p.endswith(".txt")]
        if py_paths and txt_paths:
            assert result.index(py_paths[0]) < result.index(txt_paths[0])

    def test_no_entries_returns_empty(self) -> None:
        assert score_files([], query="anything", top_n=10) == []

    def test_result_contains_strings(self, entries: list[RepoMapEntry]) -> None:
        result = score_files(entries, query="auth")
        assert all(isinstance(p, str) for p in result)

    def test_all_entries_represented_when_top_n_equals_len(
        self, entries: list[RepoMapEntry]
    ) -> None:
        result = score_files(entries, query="auth", top_n=len(entries))
        assert set(result) == {e.path for e in entries}

    def test_ties_broken_alphabetically(self) -> None:
        # Both entries score 0 (no query match) → alphabetical order
        items = [
            RepoMapEntry(path="z_module.py"),
            RepoMapEntry(path="a_module.py"),
        ]
        result = score_files(items, query="xyzzy_nomatch")
        assert result == ["a_module.py", "z_module.py"]

    def test_query_with_only_stop_words_returns_first_n(
        self, entries: list[RepoMapEntry]
    ) -> None:
        # All stop words → tokenise returns [] → empty query branch
        result = score_files(entries, query="the a is", top_n=2)
        assert len(result) == 2
        assert result == [e.path for e in entries[:2]]
