"""Base-branch selectors. Plug-in chosen at GitHubClient construction.

Two operations need a base branch:
  1. Creating a feature branch from a base (`create_branch`).
  2. Opening a PR — choosing the merge target (`open_pr`).

Selectors decouple the prompt UX from the mechanical I/O. Production wires
`InteractiveSelector`. Tests wire `FixedSelector`. TUI (Phase 11) will swap in a
panel-driven selector that surfaces the prompt in the approval pane.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol, runtime_checkable

from codepilot.observability import get_logger

_log = get_logger("github_io.prompts")


# Operation labels — keep short, used in prompts and audit events.
OP_CREATE_BRANCH = "create_branch"
OP_OPEN_PR_BASE = "open_pr_base"


@runtime_checkable
class BaseBranchSelector(Protocol):
    def select(
        self,
        *,
        operation: str,
        candidates: Sequence[str],
        default: str | None,
    ) -> str: ...


class FixedSelector:
    """Always returns the configured branch. For tests + non-interactive runs."""

    def __init__(self, branch: str) -> None:
        self._branch = branch

    def select(
        self,
        *,
        operation: str,
        candidates: Sequence[str],
        default: str | None,
    ) -> str:
        if candidates and self._branch not in candidates:
            raise ValueError(
                f"FixedSelector: configured branch {self._branch!r} "
                f"not in repo branches {list(candidates)}"
            )
        return self._branch


class DefaultBranchSelector:
    """Returns the default without prompting. Cheap fallback for CI."""

    def select(
        self,
        *,
        operation: str,
        candidates: Sequence[str],
        default: str | None,
    ) -> str:
        if not default:
            raise ValueError(f"no default branch supplied for operation {operation!r}")
        return default


class InteractiveSelector:
    """Reads from stdin. Used by the CLI runner before the TUI mounts.

    Reader/writer are injectable for tests.
    """

    def __init__(
        self,
        reader: Callable[[str], str] | None = None,
        writer: Callable[[str], None] | None = None,
    ) -> None:
        self._read = reader or input
        self._write = writer or (lambda s: print(s))

    def _prompt_label(self, operation: str) -> str:
        return {
            OP_CREATE_BRANCH: "Select BASE branch to fork from",
            OP_OPEN_PR_BASE: "Select TARGET branch to merge PR into",
        }.get(operation, f"Select base branch for {operation}")

    def select(
        self,
        *,
        operation: str,
        candidates: Sequence[str],
        default: str | None,
    ) -> str:
        if not candidates:
            raise ValueError("no candidate branches available")

        self._write("")
        self._write(self._prompt_label(operation) + ":")
        for i, name in enumerate(candidates, 1):
            tag = "  <-- default" if name == default else ""
            self._write(f"  [{i}] {name}{tag}")
        prompt_default = default or "?"

        while True:
            raw = self._read(f"Choice [{prompt_default}]: ").strip()
            if not raw:
                if default and default in candidates:
                    return default
                self._write("default missing — type a branch name or number.")
                continue
            if raw.isdigit():
                idx = int(raw)
                if 1 <= idx <= len(candidates):
                    return candidates[idx - 1]
                self._write(f"out of range; pick 1..{len(candidates)}")
                continue
            if raw in candidates:
                return raw
            self._write(f"unknown branch {raw!r}; valid: {list(candidates)}")


def resolve_base(
    selector: BaseBranchSelector,
    *,
    operation: str,
    candidates: Sequence[str],
    default: str | None,
) -> str:
    """Run selector, validate, log decision. Returns chosen branch."""
    chosen = selector.select(
        operation=operation, candidates=candidates, default=default,
    )
    if candidates and chosen not in candidates:
        raise ValueError(
            f"selector returned {chosen!r}, not among candidates {list(candidates)}"
        )
    _log.info(
        "base_branch.selected",
        operation=operation, chosen=chosen, default=default,
    )
    return chosen
