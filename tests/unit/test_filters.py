from datetime import datetime, timezone

import pytest

from codepilot.github_io.filters import is_assignable
from codepilot.github_io.models import IssueRef


def _issue(**kw) -> IssueRef:
    base = dict(
        number=1, title="t", body="", labels=(), assignees=(),
        reporter="bob", repo="acme/x", state="open",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        url="https://example.com/1",
    )
    base.update(kw)
    return IssueRef(**base)


class TestStateGate:
    def test_closed_rejected(self) -> None:
        assert is_assignable(_issue(state="closed")) is False


class TestInProgress:
    def test_in_progress_rejected(self) -> None:
        assert is_assignable(_issue(number=7), in_progress_ids={7}) is False

    def test_other_in_progress_ok(self) -> None:
        assert is_assignable(_issue(number=7), in_progress_ids={1, 2, 3}) is True


class TestLabel:
    def test_ai_label_takes_priority_over_assignment(self) -> None:
        i = _issue(labels=("ai-assignable",), assignees=("alice",))
        assert is_assignable(i) is True

    def test_custom_label(self) -> None:
        i = _issue(labels=("auto-fix",))
        assert is_assignable(i, ai_label="auto-fix") is True
        assert is_assignable(i, ai_label="ai-assignable") is True  # falls through to "no assignees"


class TestUnassignedFlow:
    def test_unassigned_no_complexity_taken(self) -> None:
        assert is_assignable(_issue(assignees=())) is True

    def test_assigned_rejected_when_no_label(self) -> None:
        assert is_assignable(_issue(assignees=("alice",))) is False


class TestComplexity:
    def test_below_threshold_taken(self) -> None:
        assert is_assignable(
            _issue(),
            complexity_estimator=lambda i: 3,
            complexity_threshold=6,
        ) is True

    def test_above_threshold_rejected(self) -> None:
        assert is_assignable(
            _issue(),
            complexity_estimator=lambda i: 9,
            complexity_threshold=6,
        ) is False

    def test_at_threshold_taken(self) -> None:
        assert is_assignable(
            _issue(),
            complexity_estimator=lambda i: 6,
            complexity_threshold=6,
        ) is True

    def test_label_bypasses_complexity(self) -> None:
        assert is_assignable(
            _issue(labels=("ai-assignable",)),
            complexity_estimator=lambda i: 99,
            complexity_threshold=6,
        ) is True


@pytest.mark.parametrize("ai_label", ["ai-assignable", "auto-fix", "claude-go"])
def test_label_alias_param(ai_label: str) -> None:
    assert is_assignable(_issue(labels=(ai_label,)), ai_label=ai_label) is True
