"""GitHub @tool wrappers for the DeepAgents orchestrator."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_community.utilities.github import GitHubAPIWrapper  # type: ignore[import]
from langchain_core.tools import tool

if TYPE_CHECKING:
    from codepilot.tui.hitl import HITLCoordinator

# Module-level HITL gate. Set once from __main__.py before orchestrator creation.
# Tools call this gate before executing destructive GitHub operations.
_hitl_gate: "HITLCoordinator | None" = None


def set_hitl_gate(gate: "HITLCoordinator | None") -> None:
    global _hitl_gate
    _hitl_gate = gate
    import sys
    print(f"[HITL-GATE] set_hitl_gate called, gate={gate is not None}", file=sys.stderr, flush=True)


def _require_approval(operation: str, details: dict[str, Any]) -> str | None:
    """Call HITL gate. Returns error string if rejected, None if approved (or no gate)."""
    from codepilot.observability.logger import get_logger
    import sys
    _log = get_logger("hitl.gate")
    gate_set = _hitl_gate is not None
    _log.info("hitl.gate_check", operation=operation, gate_set=gate_set)
    print(f"[HITL-GATE] {operation} called, gate_set={gate_set}", file=sys.stderr, flush=True)
    if _hitl_gate is None:
        _log.warning("hitl.gate_unset", operation=operation)
        return None
    try:
        # Notify TUI log immediately (separate from blocking approval call)
        app = getattr(_hitl_gate, "_app", None)
        if app is not None and hasattr(app, "post_append_log"):
            app.post_append_log(f"[HITL] gate firing for {operation}")
    except Exception:
        pass
    approved = _hitl_gate.request_approval(operation, details)
    _log.info("hitl.gate_decision", operation=operation, approved=approved)
    if not approved:
        return f"rejected: user rejected {operation}"
    return None


def _get_wrapper() -> GitHubAPIWrapper:
    from codepilot.config.settings import get_settings

    cfg = get_settings()
    if cfg.github_token:
        return GitHubAPIWrapper(
            github_access_token=cfg.github_token.get_secret_value(),
            github_repository=cfg.repo_full_name,
        )
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
    """Get a single GitHub issue by number. Returns error dict on failure."""
    try:
        wrapper = _get_wrapper()
        # Use the PyGithub repo instance directly — GitHubAPIWrapper.get_issue() has
        # inconsistent return type across LangChain versions (str vs dict vs object).
        issue = wrapper.github_repo_instance.get_issue(number=issue_number)
        return {
            "number": issue.number,
            "title": issue.title,
            "body": issue.body or "",
        }
    except Exception as exc:
        return {"error": str(exc), "number": issue_number}


@tool
def create_branch(branch_name: str, base_branch: str) -> dict | str:
    """Create a new git branch from `base_branch` (e.g. "main"). If base_branch is missing, falls back to repo default. Returns the new branch name on success, or {"error": ...} on failure."""
    try:
        wrapper = _get_wrapper()
        repo = wrapper.github_repo_instance
        # Auto-detect default branch if requested base doesn't exist
        try:
            base = repo.get_branch(base_branch)
        except Exception:
            default = repo.default_branch
            if default == base_branch:
                raise
            base = repo.get_branch(default)
            base_branch = default
        base_sha = base.commit.sha
        # If branch already exists, return success (idempotent)
        try:
            existing = repo.get_branch(branch_name)
            if existing is not None:
                return {"branch_name": branch_name, "note": "already_exists", "base_branch": base_branch}
        except Exception:
            pass
        repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_sha)
        return {"branch_name": branch_name, "base_branch": base_branch, "base_sha": base_sha}
    except Exception as exc:
        return {"error": str(exc), "branch_name": branch_name, "base_branch": base_branch}


@tool
def commit_files(branch: str, file_paths: list[str], message: str) -> dict | str:
    """Commit local file contents to a GitHub branch. Reads each file from disk. Returns error dict on merge conflict, string confirmation on success."""
    err = _require_approval(
        "commit_files",
        {"branch": branch, "files": len(file_paths), "message": message[:80]},
    )
    if err:
        return {"error": err}
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
    err = _require_approval(
        "open_pr",
        {"title": title[:80], "head": head, "base": base},
    )
    if err:
        return {"error": err}
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
