"""Local workspace management — clone/pull GitHub repos for agent editing."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

_GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


def _rmtree(path: Path) -> None:
    """Delete tree, forcing read-only files writable first (needed on Windows .git dirs)."""
    def _on_error(fn: object, p: str, _exc: object) -> None:
        os.chmod(p, stat.S_IWRITE)
        fn(p)  # type: ignore[operator]

    shutil.rmtree(path, onerror=_on_error)
_CLONE_TIMEOUT = 120
_GIT_OPTS = dict(
    capture_output=True,
    text=True,
    stdin=subprocess.DEVNULL,
    env=_GIT_ENV,
)


def _run_git(*args: str, cwd: Path | None = None, timeout: int = 60) -> None:
    try:
        subprocess.run(list(args), cwd=cwd, check=True, timeout=timeout, **_GIT_OPTS)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"git {args[1]} failed (exit {exc.returncode}): {exc.stderr.strip()}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"git {args[1]} timed out after {timeout}s") from exc


def clone_or_pull(repo_full_name: str, token: str, base_dir: Path) -> Path:
    """Clone repo to base_dir/{repo_name}/ or pull if already cloned. Returns workspace path."""
    repo_name = repo_full_name.split("/")[-1]
    workspace = base_dir / repo_name
    auth_url = f"https://x-access-token:{token}@github.com/{repo_full_name}.git"

    if (workspace / ".git").exists():
        # Fetch and hard-reset — previous agent runs may have left local changes.
        try:
            _run_git("git", "fetch", "origin", cwd=workspace)
            _run_git("git", "reset", "--hard", "origin/HEAD", cwd=workspace)
            _run_git("git", "clean", "-fd", cwd=workspace)
            return workspace
        except RuntimeError:
            # Corrupted or stale workspace — wipe and re-clone below.
            _rmtree(workspace)

    workspace.parent.mkdir(parents=True, exist_ok=True)
    _run_git("git", "clone", auth_url, str(workspace), timeout=_CLONE_TIMEOUT)
    return workspace


def cleanup(workspace: Path) -> None:
    """Delete workspace directory after task completes."""
    if workspace and workspace.exists():
        _rmtree(workspace)
