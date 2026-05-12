"""Episodic memory @tool wrappers."""
from __future__ import annotations

from langchain_core.tools import tool

SESSION_ID_DEFAULT = "default"


def _get_store():
    from codepilot.memory.episodic import EpisodicStore

    return EpisodicStore()


@tool
def query_lessons(task_description: str, repo: str, top_k: int = 3) -> list[dict]:
    """Query past lessons learned for a similar task in this repo."""
    store = _get_store()
    try:
        records = store.task_records(SESSION_ID_DEFAULT)
        results = []
        for r in records:
            if repo and r.repo != repo:
                continue
            results.append(
                {
                    "approach": r.note or "",
                    "outcome": r.outcome,
                    "files": r.files_modified,
                    "issue_type": r.task_type or "",
                }
            )
        return results[:top_k]
    except Exception:
        return []


@tool
def add_lesson(
    repo: str,
    issue_type: str,
    files: list[str],
    approach: str,
    outcome: str,
) -> str:
    """Record a lesson learned after completing a task."""
    from codepilot.memory.episodic import TaskOutcome

    store = _get_store()
    task = TaskOutcome(
        issue_id=0,
        repo=repo,
        task_type=issue_type,
        files_modified=files,
        outcome=outcome,
        note=approach,
    )
    store.record_task(session_id=SESSION_ID_DEFAULT, outcome=task)
    return f"lesson recorded: {issue_type} in {repo}"
