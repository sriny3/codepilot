"""FileEdit, EditProvider protocol, and FakeEditProvider tests."""
import pytest

from codepilot.agents.coder.edits import EditProvider, FakeEditProvider, FileEdit


# ── FileEdit ───────────────────────────────────────────────────────────────────


class TestFileEdit:
    def test_path_and_content_stored(self) -> None:
        fe = FileEdit(path="src/foo.py", content="# new\n")
        assert fe.path == "src/foo.py"
        assert fe.content == "# new\n"

    def test_is_frozen(self) -> None:
        fe = FileEdit(path="src/foo.py", content="x")
        with pytest.raises((AttributeError, TypeError)):
            fe.path = "other"  # type: ignore[misc]

    def test_equality(self) -> None:
        a = FileEdit("a.py", "content")
        b = FileEdit("a.py", "content")
        assert a == b

    def test_inequality_on_path(self) -> None:
        assert FileEdit("a.py", "x") != FileEdit("b.py", "x")

    def test_inequality_on_content(self) -> None:
        assert FileEdit("a.py", "x") != FileEdit("a.py", "y")


# ── FakeEditProvider ───────────────────────────────────────────────────────────


class TestFakeEditProvider:
    def test_returns_configured_edits(self) -> None:
        edits = [FileEdit("a.py", "content")]
        provider = FakeEditProvider(edits)
        result = provider.generate_edits(
            issue_body="fix bug", repo_map="# map", file_contents={}
        )
        assert result == edits

    def test_no_edits_by_default(self) -> None:
        provider = FakeEditProvider()
        result = provider.generate_edits(
            issue_body="x", repo_map="", file_contents={}
        )
        assert result == []

    def test_records_last_issue_body(self) -> None:
        provider = FakeEditProvider()
        provider.generate_edits(
            issue_body="fix login", repo_map="", file_contents={}
        )
        assert provider.last_issue_body == "fix login"

    def test_records_last_repo_map(self) -> None:
        provider = FakeEditProvider()
        provider.generate_edits(
            issue_body="", repo_map="# Repo: myapp", file_contents={}
        )
        assert provider.last_repo_map == "# Repo: myapp"

    def test_records_last_file_contents(self) -> None:
        provider = FakeEditProvider()
        provider.generate_edits(
            issue_body="", repo_map="", file_contents={"src/a.py": "old code"}
        )
        assert provider.last_file_contents == {"src/a.py": "old code"}

    def test_records_last_skill_prompt(self) -> None:
        provider = FakeEditProvider()
        provider.generate_edits(
            issue_body="", repo_map="", file_contents={}, skill_prompt="use TDD"
        )
        assert provider.last_skill_prompt == "use TDD"

    def test_file_contents_copied_not_aliased(self) -> None:
        provider = FakeEditProvider()
        fc = {"a.py": "original"}
        provider.generate_edits(issue_body="", repo_map="", file_contents=fc)
        fc["a.py"] = "mutated after call"
        assert provider.last_file_contents == {"a.py": "original"}

    def test_satisfies_edit_provider_protocol(self) -> None:
        provider = FakeEditProvider()
        assert isinstance(provider, EditProvider)

    def test_multiple_edits_returned(self) -> None:
        edits = [FileEdit("a.py", "1"), FileEdit("b.py", "2")]
        provider = FakeEditProvider(edits)
        result = provider.generate_edits(issue_body="", repo_map="", file_contents={})
        assert len(result) == 2
        assert result[0].path == "a.py"
        assert result[1].path == "b.py"

    def test_last_call_overwritten_on_second_call(self) -> None:
        provider = FakeEditProvider()
        provider.generate_edits(issue_body="first", repo_map="", file_contents={})
        provider.generate_edits(issue_body="second", repo_map="", file_contents={})
        assert provider.last_issue_body == "second"
