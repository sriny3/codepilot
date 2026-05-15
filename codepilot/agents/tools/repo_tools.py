"""Repository exploration @tool wrappers."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from langchain_core.tools import tool

_CACHE_FILE = ".codepilot/repo_map.json"


def _git_head_sha(root: str) -> str:
    """Return current git HEAD SHA for cache invalidation."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def _resolve_root(root_path: str) -> Path:
    """Return Path for root_path; falls back to current directory when empty."""
    if root_path and root_path.strip():
        return Path(root_path)
    return Path(".").resolve()


@tool
def build_repo_map(root_path: str = "", max_tokens: int = 4000) -> str:
    """Build a token-budget-aware repository map. Pass root_path="" to use the configured REPO_PATH. Returns map text suitable for LLM context."""
    try:
        from codepilot.agents.repo_explorer.map import RepoMap

        resolved = _resolve_root(root_path)
        repo_map = RepoMap.build(resolved, max_tokens=max_tokens)
        return repo_map.to_text()
    except Exception as exc:
        return f"build_repo_map failed: {exc}"


@tool
def retrieve_relevant_files(issue_body: str, repo_root: str = "", top_k: int = 10) -> list[str]:
    """Retrieve the top-K files most relevant to an issue using TF-IDF scoring. Pass repo_root="" to use the configured REPO_PATH."""
    try:
        from codepilot.agents.repo_explorer.map import RepoMap
        from codepilot.agents.repo_explorer.scorer import score_files

        resolved = _resolve_root(repo_root)
        repo_map = RepoMap.build(resolved, max_tokens=8000)
        return score_files(repo_map.entries, query=issue_body, top_n=top_k)
    except Exception:
        return []


@tool
def cache_repo_map(map_text: str, root_path: str = "") -> str | None:
    """Cache repo map text alongside the current git HEAD SHA for invalidation. Pass root_path="" to use the configured REPO_PATH. Returns None on success or an error string."""
    try:
        resolved = _resolve_root(root_path)
        cache_dir = resolved / ".codepilot"
        cache_dir.mkdir(parents=True, exist_ok=True)
        sha = _git_head_sha(str(resolved))
        (cache_dir / "repo_map.json").write_text(
            json.dumps({"sha": sha, "map": map_text}), encoding="utf-8"
        )
        return None
    except Exception as exc:
        return f"cache write failed: {exc}"


@tool
def load_cached_repo_map(root_path: str = "") -> str | None:
    """Load cached repo map. Pass root_path="" to use the configured REPO_PATH. Returns None if cache is missing or the git SHA has changed."""
    resolved = _resolve_root(root_path)
    cache_file = resolved / _CACHE_FILE
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        if data.get("sha") != _git_head_sha(str(resolved)):
            return None
        return data.get("map")
    except Exception:
        return None
