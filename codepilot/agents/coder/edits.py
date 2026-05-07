"""Edit types and provider protocol for the Coder agent."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class FileEdit:
    """A single file change produced by an EditProvider."""

    path: str    # sandbox-relative path, forward slashes
    content: str # complete new file content (not a diff)


@runtime_checkable
class EditProvider(Protocol):
    """Interface satisfied by any object that can generate code edits.

    Implement this to plug in an LLM, a rule-based system, or a test fake.
    The CoderAgent calls exactly one method: ``generate_edits``.
    """

    def generate_edits(
        self,
        *,
        issue_body: str,
        repo_map: str,
        file_contents: dict[str, str],
        skill_prompt: str | None = None,
    ) -> list[FileEdit]: ...


class FakeEditProvider:
    """Deterministic edit provider for tests.

    Returns pre-configured edits regardless of inputs. Records the last
    call arguments so tests can assert what the CoderAgent passed in.
    """

    def __init__(self, edits: list[FileEdit] | None = None) -> None:
        self._edits: list[FileEdit] = edits or []
        self.last_issue_body: str | None = None
        self.last_repo_map: str | None = None
        self.last_file_contents: dict[str, str] | None = None
        self.last_skill_prompt: str | None = None

    def generate_edits(
        self,
        *,
        issue_body: str,
        repo_map: str,
        file_contents: dict[str, str],
        skill_prompt: str | None = None,
    ) -> list[FileEdit]:
        self.last_issue_body = issue_body
        self.last_repo_map = repo_map
        self.last_file_contents = dict(file_contents)  # copy, not alias
        self.last_skill_prompt = skill_prompt
        return list(self._edits)
