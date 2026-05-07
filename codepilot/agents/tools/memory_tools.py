"""Episodic memory @tool wrappers."""
from __future__ import annotations

from langchain_core.tools import tool


def _get_store():
    from codepilot.memory.episodic import EpisodicStore

    return EpisodicStore()


@tool
def query_lessons(task_description: str, repo: str, top_k: int = 3) -> list[dict]:
    """Query past lessons learned for a similar task in this repo."""
    store = _get_store()
    try:
        results = store.query(task_description, repo=repo, top_k=top_k)
        return results if isinstance(results, list) else []
    except Exception:
        return []


@tool
def add_lesson(
    repo: str,
    issue_type: str,
    files: list[str],
    approach: str,
    outcome: str,
) -> None:
    """Record a lesson learned after completing a task."""
    store = _get_store()
    store.add(
        repo=repo,
        issue_type=issue_type,
        files=files,
        approach=approach,
        outcome=outcome,
    )
