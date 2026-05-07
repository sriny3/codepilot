"""File relevance scorer — keyword matching between an issue query and repo entries."""
from __future__ import annotations

import re

from codepilot.agents.repo_explorer.map import RepoMapEntry


_STOP_WORDS: frozenset[str] = frozenset({
    "a", "an", "the", "is", "in", "it", "of", "to", "and", "or", "for",
    "on", "with", "that", "this", "was", "are", "be", "as", "at", "by",
    "from", "have", "had", "not", "but", "we", "i", "you", "he", "she",
    "they", "do", "does", "did", "will", "would", "could", "should",
})

# Extension bonuses applied as a multiplier on keyword score.
_EXT_BONUS: dict[str, float] = {
    ".py": 1.0, ".ts": 1.0, ".tsx": 1.0, ".js": 0.8, ".jsx": 0.8,
    ".go": 1.0, ".rs": 1.0, ".java": 0.9, ".rb": 0.9,
    ".md": 0.3, ".txt": 0.2, ".json": 0.2, ".yaml": 0.2, ".yml": 0.2,
    ".toml": 0.2, ".cfg": 0.1, ".ini": 0.1,
}


def _tokenise(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, stop-words and single chars removed."""
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 1]


def score_files(
    entries: list[RepoMapEntry],
    *,
    query: str,
    top_n: int = 20,
) -> list[str]:
    """Return the top-N file paths most relevant to `query`.

    Scoring per entry:
    - +2 per query token found in the file's path segments
    - +1 per query token found in any symbol name token
    - Extension bonus (0.0–1.0) multiplied by total keyword score

    Empty query → return first `top_n` entries in their original order.
    Ties broken alphabetically by path.
    """
    query_tokens = set(_tokenise(query))
    if not query_tokens:
        return [e.path for e in entries[:top_n]]

    scored: list[tuple[float, str]] = []
    for entry in entries:
        path_tokens = set(re.findall(r"[a-z0-9]+", entry.path.lower()))
        sym_tokens: set[str] = set()
        for sym in entry.symbols:
            sym_tokens.update(re.findall(r"[a-z0-9]+", sym.lower()))

        kw_score = sum(2 for t in query_tokens if t in path_tokens)
        kw_score += sum(1 for t in query_tokens if t in sym_tokens)

        ext_part = entry.path.rsplit(".", 1)
        ext = "." + ext_part[-1] if len(ext_part) == 2 else ""
        bonus = _EXT_BONUS.get(ext, 0.5)
        total = kw_score * (1.0 + bonus) if kw_score > 0 else 0.0

        scored.append((total, entry.path))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return [path for _, path in scored[:top_n]]
