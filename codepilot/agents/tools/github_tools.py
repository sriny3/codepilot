"""GitHub @tool wrappers for the DeepAgents orchestrator."""
from __future__ import annotations

from langchain_community.utilities.github import GitHubAPIWrapper  # type: ignore[import]
from langchain_core.tools import tool


def _get_wrapper() -> GitHubAPIWrapper:
    from codepilot.config.settings import get_settings

    cfg = get_settings()
    return GitHubAPIWrapper(
        github_app_id=cfg.github_app_id,
        github_app_private_key=cfg.github_app_private_key.get_secret_value(),
        github_repository=cfg.repo_full_name,
    )


@tool
def list_open_issues(labels: list[str], exclude_ids: list[int]) -> list[dict]:
    """List open GitHub issues filtered by labels, excluding specific issue IDs."""
    wrapper = _get_wrapper()
    raw = wrapper.get_issues()
    issues = []
    for issue in raw:
        if issue.get("number") in exclude_ids:
            continue
        issue_labels = [lb.get("name", "") for lb in issue.get("labels", [])]
        if labels and not any(lb in issue_labels for lb in labels):
            continue
        issues.append({
            "number": issue["number"],
            "title": issue["title"],
            "body": issue.get("body", ""),
        })
    return issues


@tool
def get_issue(issue_number: int) -> dict:
    """Get a single GitHub issue by number."""
    wrapper = _get_wrapper()
    issue = wrapper.get_issue(issue_number)
    return {
        "number": issue_number,
        "title": issue.get("title", ""),
        "body": issue.get("body", ""),
    }


@tool
def create_branch(branch_name: str, base_branch: str) -> str:
    """Create a new git branch from a base branch. Returns the new branch name."""
    wrapper = _get_wrapper()
    wrapper.create_branch(branch_name)
    return branch_name


@tool
def commit_files(branch: str, file_paths: list[str], message: str) -> dict | str:
    """Commit a list of file paths to a branch. Returns error dict on merge conflict."""
    try:
        wrapper = _get_wrapper()
        for path in file_paths:
            wrapper.create_file(path, message, "", branch=branch)
        return f"Committed {len(file_paths)} file(s) to {branch}"
    except Exception as exc:
        msg = str(exc).lower()
        if "merge conflict" in msg or "409" in msg or "422" in msg:
            return {"error": "merge_conflict", "message": str(exc)}
        raise


@tool
def open_pr(
    title: str,
    body: str,
    head: str,
    base: str,
    labels: list[str],
    reviewers: list[str],
) -> dict:
    """Open a GitHub pull request. Returns dict with pr_number and url."""
    wrapper = _get_wrapper()
    pr = wrapper.create_pull(title=title, body=body, head=head, base=base)
    return {
        "pr_number": getattr(pr, "number", 0),
        "url": getattr(pr, "html_url", ""),
    }
