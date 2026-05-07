"""Unified diff generation and application for sandbox files.

generate_diff / generate_diff_from_content produce standard unified-diff output
compatible with `git diff` and `patch`. apply_diff applies a unified diff
using a pure-Python hunk applier (no external `patch` binary required).
"""
from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from codepilot.sandbox.local import LocalSandbox


# ── Generation ─────────────────────────────────────────────────────────────────


def generate_diff(
    original: Path,
    modified: Path,
    *,
    label_a: str | None = None,
    label_b: str | None = None,
    context_lines: int = 3,
) -> str:
    """Return a unified diff string between two files on disk.

    Labels default to `a/<name>` / `b/<name>` to match git-diff output shape.
    Returns empty string when files are identical.
    """
    a_text = original.read_text(encoding="utf-8") if original.exists() else ""
    b_text = modified.read_text(encoding="utf-8") if modified.exists() else ""
    return generate_diff_from_content(
        a_text,
        b_text,
        label_a=label_a or f"a/{original.name}",
        label_b=label_b or f"b/{modified.name}",
        context_lines=context_lines,
    )


def generate_diff_from_content(
    original: str,
    modified: str,
    *,
    label_a: str = "a/file",
    label_b: str = "b/file",
    context_lines: int = 3,
) -> str:
    """Return a unified diff from two content strings.

    Returns empty string when contents are identical.
    """
    a_lines = original.splitlines(keepends=True)
    b_lines = modified.splitlines(keepends=True)
    result = "".join(
        difflib.unified_diff(
            a_lines,
            b_lines,
            fromfile=label_a,
            tofile=label_b,
            n=context_lines,
        )
    )
    return result


def generate_sandbox_diff(
    sandbox: "LocalSandbox",
    source_root: Path,
    files: list[str | Path],
    *,
    context_lines: int = 3,
) -> str:
    """Diff every listed file between `source_root` and the sandbox.

    Files that exist only in the sandbox appear as pure additions; files that
    exist only in `source_root` appear as pure deletions. Unchanged files
    produce no output.
    """
    parts: list[str] = []
    source_root = source_root.resolve()

    for rel in files:
        rel_str = str(rel).replace("\\", "/")
        orig = source_root / rel
        mod = sandbox.root / rel

        orig_text = orig.read_text(encoding="utf-8") if orig.exists() else ""
        mod_text = mod.read_text(encoding="utf-8") if mod.exists() else ""

        diff = generate_diff_from_content(
            orig_text,
            mod_text,
            label_a=f"a/{rel_str}",
            label_b=f"b/{rel_str}",
            context_lines=context_lines,
        )
        if diff:
            parts.append(diff)

    return "\n".join(parts)


# ── Application ────────────────────────────────────────────────────────────────

# Matches unified-diff hunk headers: @@ -old_start[,old_count] +new_start[,new_count] @@
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _apply_hunks(original_lines: list[str], diff_text: str) -> list[str]:
    """Pure-Python unified-diff applier.

    Works on a list of lines (each with trailing newline). Returns the new
    content as a list of lines.
    """
    result = list(original_lines)
    offset = 0  # cumulative line-number shift due to previously applied hunks

    diff_lines = diff_text.splitlines(keepends=True)
    i = 0
    while i < len(diff_lines):
        m = _HUNK_RE.match(diff_lines[i])
        if not m:
            i += 1
            continue

        old_start = int(m.group(1)) - 1        # convert to 0-based
        old_count = int(m.group(2)) if m.group(2) is not None else 1
        i += 1

        new_lines: list[str] = []
        old_consumed = 0

        while i < len(diff_lines):
            line = diff_lines[i]
            if _HUNK_RE.match(line):
                break
            if line.startswith("--- ") or line.startswith("+++ "):
                break
            if not line:
                i += 1
                continue
            marker = line[0]
            content = line[1:]
            if marker == " ":
                new_lines.append(content)
                old_consumed += 1
            elif marker == "+":
                new_lines.append(content)
            elif marker == "-":
                old_consumed += 1
            i += 1

        actual_start = old_start + offset
        result[actual_start : actual_start + old_consumed] = new_lines
        offset += len(new_lines) - old_consumed

    return result


def apply_diff(target: Path, diff_text: str) -> None:
    """Apply a unified diff in-place to `target`.

    Uses a pure-Python hunk applier; no external `patch` binary required.
    Skips silently when `diff_text` is blank (idempotent for no-op diffs).
    """
    if not diff_text.strip():
        return

    original = target.read_text(encoding="utf-8") if target.exists() else ""
    original_lines = original.splitlines(keepends=True)
    new_lines = _apply_hunks(original_lines, diff_text)
    target.write_text("".join(new_lines), encoding="utf-8")
