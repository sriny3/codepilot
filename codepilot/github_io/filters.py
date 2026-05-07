"""Issue selection rules. Pure functions — testable without GitHub."""
from __future__ import annotations

from collections.abc import Iterable

from codepilot.github_io.models import IssueRef

DEFAULT_AI_LABEL = "ai-assignable"


def is_assignable(
    issue: IssueRef,
    *,
    in_progress_ids: Iterable[int] = (),
    ai_label: str = DEFAULT_AI_LABEL,
    complexity_estimator: "ComplexityFn | None" = None,
    complexity_threshold: int | None = None,
) -> bool:
    """Decide whether the orchestrator should pick up `issue`.

    Selection rules (matches plan Component 1):
      1. Skip closed issues.
      2. Skip if already in progress.
      3. Take if labelled `ai-assignable`.
      4. Else take if unassigned AND (complexity unknown OR ≤ threshold).
    """
    if issue.state != "open":
        return False
    if issue.number in set(in_progress_ids):
        return False
    if ai_label in issue.labels:
        return True
    if issue.assignees:
        return False
    if complexity_estimator is None or complexity_threshold is None:
        return True
    return complexity_estimator(issue) <= complexity_threshold


# Type alias for complexity estimators (defined externally; Phase 10 owns it).
from collections.abc import Callable  # noqa: E402

ComplexityFn = Callable[[IssueRef], int]
