"""Issue classifier — keyword rules first, LLM fallback."""
from __future__ import annotations

_KEYWORD_RULES: list[tuple[list[str], str]] = [
    (["fix", "bug", "error", "crash", "fail", "exception", "broken", "regression"], "bug_fix"),
    (["add", "feature", "implement", "support", "new", "create", "build"], "feature_addition"),
    (["bump", "upgrade", "update", "dependency", "version", "pin", "downgrade"], "dependency_update"),
    (["doc", "readme", "comment", "typo", "docstring", "documentation"], "documentation"),
    (["config", "env", "setting", "yaml", "toml", "environment", "configure"], "config_change"),
]


def classify_issue(title: str, body: str, labels: list[str]) -> str:
    """Return the issue type string. Keyword rules first; returns best match."""
    text = f"{title} {body} {' '.join(labels)}".lower()

    scores: dict[str, int] = {}
    for keywords, category in _KEYWORD_RULES:
        count = sum(1 for kw in keywords if kw in text)
        if count > 0:
            scores[category] = scores.get(category, 0) + count

    if scores:
        return max(scores, key=lambda k: scores[k])

    return "bug_fix"
