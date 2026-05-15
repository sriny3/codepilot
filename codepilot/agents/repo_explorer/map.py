"""Repository map builder — token-budget-aware directory + symbol summary."""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


_SKIP_DIRS: frozenset[str] = frozenset({
    ".git", ".hg", ".svn",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".venv", "venv", "env",
    "node_modules", ".next", "dist", "build",
    ".tox", ".nox",
})

# Files that must never appear in the repo map (secrets / gitignore patterns)
_SKIP_FILES: frozenset[str] = frozenset({
    ".env", ".env.example", ".env.local", ".env.test", ".env.production",
    ".gitignore", ".gitattributes", ".dockerignore",
})

_CHARS_PER_TOKEN: int = 4  # rough estimate: ~4 chars per LLM token


@dataclass(frozen=True)
class RepoMapEntry:
    path: str                          # repo-root-relative, forward slashes
    symbols: tuple[str, ...] = field(default_factory=tuple)
    size_bytes: int = 0


def _extract_symbols(source_path: Path) -> list[str]:
    """Return top-level class and function names from a Python file.

    Returns [] on syntax error or any I/O failure — never raises.
    """
    try:
        tree = ast.parse(source_path.read_bytes())
    except (SyntaxError, OSError, ValueError):
        return []
    symbols: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(node.name)
    return symbols


class RepoMap:
    """Snapshot of a repository's file structure and key Python symbols."""

    def __init__(self, entries: list[RepoMapEntry], repo_root: Path) -> None:
        self.entries = entries
        self.repo_root = repo_root

    @classmethod
    def build(
        cls,
        root: Path,
        *,
        max_tokens: int = 4000,
    ) -> "RepoMap":
        """Walk `root`, extract symbols from .py files, honour token budget.

        Directories in ``_SKIP_DIRS`` and directories whose names start with
        ``.`` are excluded.  Files are added in alphabetical path order until
        the character budget (``max_tokens * _CHARS_PER_TOKEN``) is exhausted;
        the first file is always included regardless of budget.
        """
        root = root.resolve()
        entries: list[RepoMapEntry] = []
        budget_chars = max_tokens * _CHARS_PER_TOKEN
        used_chars = 0

        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel_parts = path.relative_to(root).parts
            # Skip if any *parent* directory is hidden or in the skip list
            if any(
                part.startswith(".") or part in _SKIP_DIRS
                for part in rel_parts[:-1]
            ):
                continue
            # Skip sensitive files by exact name or extension
            fname = rel_parts[-1]
            if fname in _SKIP_FILES or Path(fname).suffix in {".pem", ".key", ".p12", ".pfx"}:
                continue

            rel = path.relative_to(root).as_posix()
            symbols: list[str] = []
            if path.suffix == ".py":
                symbols = _extract_symbols(path)

            try:
                size = path.stat().st_size
            except OSError:
                size = 0

            # Rough char cost: path + bracketed symbol list
            line_cost = len(rel) + sum(len(s) + 2 for s in symbols) + 4
            if used_chars + line_cost > budget_chars and entries:
                break  # budget exhausted; first entry is always kept

            used_chars += line_cost
            entries.append(
                RepoMapEntry(path=rel, symbols=tuple(symbols), size_bytes=size)
            )

        return cls(entries, root)

    def to_text(self) -> str:
        """Render as a human-readable (LLM-consumable) string."""
        lines: list[str] = [f"# Repo: {self.repo_root.name}", ""]
        for entry in self.entries:
            if entry.symbols:
                sym_str = ", ".join(entry.symbols)
                lines.append(f"  {entry.path}  [{sym_str}]")
            else:
                lines.append(f"  {entry.path}")
        return "\n".join(lines) + "\n"

    def token_estimate(self) -> int:
        """Rough token count for the rendered text (chars // 4)."""
        return len(self.to_text()) // _CHARS_PER_TOKEN

    def save(self, path: Path) -> None:
        """Write the rendered map to `path`, creating parent dirs."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_text(), encoding="utf-8")
