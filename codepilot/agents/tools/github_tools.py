"""GitHub @tool wrappers for the DeepAgents orchestrator."""
from __future__ import annotations

from pathlib import Path

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
    """List open GitHub issues. Pass empty `labels=[]` to return all issues. Pass `exclude_ids` to skip issues being processed."""
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
            "labels": issue_labels,
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
    """Create a new git branch from `base_branch`. Returns the new branch name."""
    wrapper = _get_wrapper()
    repo = wrapper.github_repo_instance
    base_sha = repo.get_branch(base_branch).commit.sha
    repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_sha)
    return branch_name


@tool
def commit_files(branch: str, file_paths: list[str], message: str) -> dict | str:
    """Commit local file contents to a GitHub branch. Reads each file from disk. Returns error dict on merge conflict, string confirmation on success."""
    try:
        wrapper = _get_wrapper()
        committed = []
        for path in file_paths:
            try:
                content = Path(path).read_text(encoding="utf-8")
            except FileNotFoundError:
                content = ""  # file deleted or not found — skip content
            wrapper.create_file(path, message, content, branch=branch)
            committed.append(path)
        return f"Committed {len(committed)} file(s) to {branch}"
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
    """Open a GitHub pull request. Applies labels and reviewer requests (best-effort). Returns pr_number and url."""
    wrapper = _get_wrapper()
    pr = wrapper.create_pull(title=title, body=body, head=head, base=base)
    pr_number = getattr(pr, "number", 0)
    pr_url = getattr(pr, "html_url", "")

    # Apply labels and reviewers via PyGithub if provided
    if labels or reviewers:
        try:
            gh_pr = wrapper.github_repo_instance.get_pull(pr_number)
            if labels:
                gh_pr.add_to_labels(*labels)
            if reviewers:
                gh_pr.create_review_request(reviewers=reviewers)
        except Exception:
            pass  # labels/reviewers are best-effort; don't fail the PR creation

    return {"pr_number": pr_number, "url": pr_url}
