from datetime import datetime, timezone

from codepilot.github_io.models import IssueRef
from tests.unit._gh_fakes import FakeIssue, FakeLabel, FakeUser


class TestIssueRefFromPygithub:
    def test_basic_fields(self) -> None:
        i = FakeIssue(
            number=42, title="Bug", body="repro steps",
            labels=[FakeLabel("bug"), FakeLabel("ai-assignable")],
            assignees=[],
            user=FakeUser("alice"),
            created_at=datetime(2026, 5, 4, tzinfo=timezone.utc),
            html_url="https://github.com/acme/x/issues/42",
        )
        ref = IssueRef.from_pygithub(i, "acme/x")
        assert ref.number == 42
        assert ref.title == "Bug"
        assert ref.body == "repro steps"
        assert ref.labels == ("bug", "ai-assignable")
        assert ref.assignees == ()
        assert ref.reporter == "alice"
        assert ref.repo == "acme/x"
        assert ref.url.endswith("/issues/42")

    def test_none_safe(self) -> None:
        i = FakeIssue(number=1, title=None, body=None, user=None)  # type: ignore[arg-type]
        ref = IssueRef.from_pygithub(i, "acme/x")
        assert ref.title == ""
        assert ref.body == ""
        assert ref.reporter is None

    def test_immutable(self) -> None:
        i = FakeIssue(number=1)
        ref = IssueRef.from_pygithub(i, "acme/x")
        import dataclasses
        assert dataclasses.is_dataclass(ref)
        # frozen=True → assignment raises FrozenInstanceError
        import pytest
        with pytest.raises(dataclasses.FrozenInstanceError):
            ref.title = "x"  # type: ignore[misc]
