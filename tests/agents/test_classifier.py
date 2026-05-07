"""Tests for issue classifier — keyword rules ≥ 90% accuracy."""
from __future__ import annotations

import pytest


_FIXTURES: list[tuple[str, str, list[str], str]] = [
    ("fix null pointer crash", "App crashes when user logs out", [], "bug_fix"),
    ("error in authentication", "TypeError thrown on login", [], "bug_fix"),
    ("add dark mode feature", "Please implement dark theme support", [], "feature_addition"),
    ("implement CSV export", "We need to export data to CSV", [], "feature_addition"),
    ("bump requests to 2.32", "upgrade requests dependency", [], "dependency_update"),
    ("update pydantic version", "pydantic 2.0 compatibility", [], "dependency_update"),
    ("fix typo in README", "doc update for installation guide", [], "documentation"),
    ("update comments in auth", "add docstrings to auth module", [], "documentation"),
    ("update env config", "change yaml settings for deployment", [], "config_change"),
    ("fix toml setting", "environment variable missing", [], "config_change"),
]


@pytest.mark.parametrize("title,body,labels,expected", _FIXTURES)
def test_classify_keyword_rules(title: str, body: str, labels: list[str], expected: str) -> None:
    from codepilot.orchestrator.classifier import classify_issue

    result = classify_issue(title, body, labels)
    assert result == expected, f"'{title}' → got {result!r}, expected {expected!r}"


def test_classify_accuracy_ge_90() -> None:
    from codepilot.orchestrator.classifier import classify_issue

    correct = sum(
        1
        for title, body, labels, expected in _FIXTURES
        if classify_issue(title, body, labels) == expected
    )
    accuracy = correct / len(_FIXTURES)
    assert accuracy >= 0.90, f"Classifier accuracy {accuracy:.0%} < 90%"


def test_classify_unknown_returns_string() -> None:
    from codepilot.orchestrator.classifier import classify_issue

    result = classify_issue("miscellaneous task xyz", "", [])
    assert isinstance(result, str)
    assert len(result) > 0
