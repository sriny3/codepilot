"""GitHub @tool wrappers for the DeepAgents orchestrator."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_community.utilities.github import GitHubAPIWrapper  # type: ignore[import]
from langchain_core.tools import tool

if TYPE_CHECKING:
    from codepilot.tui.hitl import HITLCoordinator


_TRACE_PATH = Path("logs/tool-trace.log")


def _trace(name: str, **kw: Any) -> None:
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    summary = ", ".join(f"{k}={str(v)[:80]!r}" for k, v in kw.items())
    line = f"{ts} [TOOL-CALL] {name}({summary})"
    print(line, file=sys.stderr, flush=True)
    try:
        _TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _TRACE_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def _trace_result(name: str, result: Any) -> None:
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"{ts} [TOOL-RESULT] {name} -> {str(result)[:300]}"
    print(line, file=sys.stderr, flush=True)
    try:
        with _TRACE_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass

# Module-level HITL gate. Set once from __main__.py before orchestrator creation.
# Tools call this gate before executing destructive GitHub operations.
_hitl_gate: "HITLCoordinator | None" = None


def set_hitl_gate(gate: "HITLCoordinator | None") -> None:
    global _hitl_gate
    _hitl_gate = gate
    print(f"[HITL-GATE] set_hitl_gate called, gate={gate is not None}", file=sys.stderr, flush=True)


def _require_approval(operation: str, details: dict[str, Any]) -> str | None:
    """Call HITL gate. Returns error string if rejected, None if approved (or no gate)."""
    from codepilot.observability.logger import get_logger
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


def _get_repo():
    """Direct PyGithub access — bypasses GitHubAPIWrapper which has parsing bugs."""
    from codepilot.config.settings import get_settings
    from github import Github

    cfg = get_settings()
    if cfg.github_token:
        gh = Github(cfg.github_token.get_secret_value())
    else:
        from github import Auth, GithubIntegration
        auth = Auth.AppAuth(int(cfg.github_app_id), cfg.github_app_private_key.get_secret_value())
        integration = GithubIntegration(auth=auth)
        # Use first installation's token
        installations = integration.get_installations()
        if installations.totalCount == 0:
            raise RuntimeError("GitHub App has no installations")
        installation = installations[0]
        gh = installation.get_github_for_installation()
    return gh.get_repo(cfg.repo_full_name)


@tool
def list_open_issues(labels: list[str], exclude_ids: list[int]) -> list[dict]:
    """List open GitHub issues. Pass empty `labels=[]` to return all issues. Pass `exclude_ids` to skip issues being processed."""
    _trace("list_open_issues", labels=labels)
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
    _trace("get_issue", issue_number=issue_number)
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
    import traceback
    _trace("create_branch", branch_name=branch_name, base_branch=base_branch)
    result: Any
    try:
        repo = _get_repo()
        try:
            base = repo.get_branch(base_branch)
        except Exception:
            default = repo.default_branch
            if default == base_branch:
                raise
            base = repo.get_branch(default)
            base_branch = default
        base_sha = base.commit.sha
        try:
            existing = repo.get_branch(branch_name)
            if existing is not None:
                result = {"branch_name": branch_name, "note": "already_exists", "base_branch": base_branch}
                _trace_result("create_branch", result)
                return result
        except Exception:
            pass
        repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_sha)
        result = {"branch_name": branch_name, "base_branch": base_branch, "base_sha": base_sha}
    except Exception as exc:
        tb = traceback.format_exc()
        # Write full traceback to trace file for diagnosis
        try:
            with _TRACE_PATH.open("a", encoding="utf-8") as fh:
                fh.write(f"--- create_branch traceback ---\n{tb}\n--- end ---\n")
        except Exception:
            pass
        result = {"error": f"{type(exc).__name__}: {exc}", "branch_name": branch_name, "base_branch": base_branch}
    _trace_result("create_branch", result)
    return result


@tool
def commit_files(branch: str, file_paths: list[str], message: str) -> dict | str:
    """Commit local file contents to a GitHub branch. Reads each file from disk. Returns error dict on merge conflict, string confirmation on success."""
    _trace("commit_files", branch=branch, files=len(file_paths), message=message[:60])
    err = _require_approval(
        "commit_files",
        {
            "value": f"Commit {len(file_paths)} file(s) to branch '{branch}'",
            "branch": branch,
            "files": len(file_paths),
            "message": message[:120],
            "paths": ", ".join(p.rsplit("/", 1)[-1] for p in file_paths[:6]),
        },
    )
    if err:
        result: Any = {"error": err}
        _trace_result("commit_files", result)
        return result
    import traceback
    try:
        repo = _get_repo()
        committed = []
        for path in file_paths:
            try:
                content = Path(path).read_text(encoding="utf-8")
            except FileNotFoundError:
                content = ""
            # Path inside repo is the relative file_path. If user passed an absolute
            # workspace path, strip it so the GitHub path is repo-relative.
            repo_path = path
            for prefix in (".codepilot/workspace/",):
                idx = path.find(prefix)
                if idx >= 0:
                    after = path[idx + len(prefix):]
                    parts = after.split("/", 1)
                    repo_path = parts[1] if len(parts) > 1 else after
                    break
            # Update if file exists, else create
            try:
                existing = repo.get_contents(repo_path, ref=branch)
                repo.update_file(repo_path, message, content, existing.sha, branch=branch)
            except Exception:
                repo.create_file(repo_path, message, content, branch=branch)
            committed.append(repo_path)
        result = f"Committed {len(committed)} file(s) to {branch}: {committed}"
    except Exception as exc:
        try:
            with _TRACE_PATH.open("a", encoding="utf-8") as fh:
                fh.write(f"--- commit_files traceback ---\n{traceback.format_exc()}\n--- end ---\n")
        except Exception:
            pass
        msg = str(exc).lower()
        if "merge conflict" in msg or "409" in msg or "422" in msg:
            result = {"error": "merge_conflict", "message": str(exc)}
        else:
            result = {"error": f"{type(exc).__name__}: {exc}"}
    _trace_result("commit_files", result)
    return result


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
    _trace("open_pr", title=title[:60], head=head, base=base)
    # Build PR compare URL for visibility (repo full name comes from settings)
    compare_url = ""
    try:
        from codepilot.config.settings import get_settings
        compare_url = f"https://github.com/{get_settings().repo_full_name}/compare/{base}...{head}"
    except Exception:
        pass
    err = _require_approval(
        "open_pr",
        {
            "value": f"Open PR: {title[:120]}",
            "head": head,
            "base": base,
            "labels": ", ".join(labels) if labels else "(none)",
            "reviewers": ", ".join(reviewers) if reviewers else "(none)",
            "compare": compare_url,
        },
    )
    if err:
        result: Any = {"error": err}
        _trace_result("open_pr", result)
        return result
    import traceback
    try:
        repo = _get_repo()
        pr = repo.create_pull(title=title, body=body, head=head, base=base)
        pr_number = pr.number
        pr_url = pr.html_url
        if labels:
            try:
                pr.add_to_labels(*labels)
            except Exception:
                pass
        if reviewers:
            try:
                pr.create_review_request(reviewers=reviewers)
            except Exception:
                pass
        result = {"pr_number": pr_number, "url": pr_url}
    except Exception as exc:
        try:
            with _TRACE_PATH.open("a", encoding="utf-8") as fh:
                fh.write(f"--- open_pr traceback ---\n{traceback.format_exc()}\n--- end ---\n")
        except Exception:
            pass
        result = {"error": f"{type(exc).__name__}: {exc}"}
    _trace_result("open_pr", result)
    return result
