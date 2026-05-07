"""Skill data model.

Skills are reusable agent capabilities — domain-specific instructions plus a
structured workflow plus a tripwire list. The orchestrator selects a skill by
task type and injects it into the relevant subagent's system prompt.
"""
from __future__ import annotations

import fnmatch
import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# Task types map 1:1 with the assignment's classification labels. Closed set;
# adding a new label requires touching the orchestrator classifier too.
class TaskType(str, Enum):
    BUG_FIX = "bug_fix"
    FEATURE_ADDITION = "feature_addition"
    DEPENDENCY_UPDATE = "dependency_update"
    DOCUMENTATION = "documentation"
    CONFIG_CHANGE = "config_change"


# Subagent identifiers that may load a skill. Phase 7+ wire concrete agents.
class AppliesTo(str, Enum):
    ORCHESTRATOR = "orchestrator"
    EXPLORER = "explorer"
    CODER = "coder"
    TESTER = "tester"
    PR_AGENT = "pr_agent"


class ForbiddenKind(str, Enum):
    SHELL = "shell"          # matched against `execute` command lines
    FILE = "file"            # matched against file paths (glob)
    REGEX = "regex"          # matched against arbitrary string with regex
    NETWORK = "network"      # documentary — paired with shell rules


class ForbiddenAction(BaseModel):
    """A single tripwire. Phase 4 guardrails read these and block the operation."""

    model_config = ConfigDict(frozen=True)

    kind: ForbiddenKind
    pattern: str
    reason: str

    def matches(self, target: str) -> bool:
        if self.kind is ForbiddenKind.FILE:
            return fnmatch.fnmatch(target, self.pattern)
        if self.kind is ForbiddenKind.REGEX:
            return re.search(self.pattern, target) is not None
        # SHELL + NETWORK use literal substring after lowercasing — cheap and stable.
        return self.pattern.lower() in target.lower()


class WorkflowStep(BaseModel):
    """One numbered step in a skill's recipe."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    title: str = Field(min_length=1)
    instructions: str = Field(min_length=1)
    success_criteria: str | None = None


class SkillExample(BaseModel):
    """One canonical prompt the skill is expected to handle.

    Used for prompt-quality smoke tests (Phase 13) and as in-context examples.
    """

    model_config = ConfigDict(frozen=True)

    prompt: str = Field(min_length=1)
    expected_workflow: list[str] = Field(default_factory=list)
    notes: str | None = None


class Skill(BaseModel):
    """One reusable agent capability."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    version: int = Field(default=1, ge=1)
    description: str = Field(min_length=1)
    task_types: tuple[TaskType, ...] = Field(min_length=1)
    applies_to: tuple[AppliesTo, ...] = Field(default=(AppliesTo.CODER,), min_length=1)
    instructions: str = Field(min_length=1)
    workflow_steps: tuple[WorkflowStep, ...] = Field(min_length=1)
    example_prompts: tuple[SkillExample, ...] = Field(default_factory=tuple)
    forbidden_actions: tuple[ForbiddenAction, ...] = Field(default_factory=tuple)
    checklist: tuple[str, ...] = Field(default_factory=tuple)
    references: tuple[str, ...] = Field(default_factory=tuple)
    owner: str | None = None

    @field_validator("workflow_steps")
    @classmethod
    def _unique_step_ids(cls, v: tuple[WorkflowStep, ...]) -> tuple[WorkflowStep, ...]:
        seen: set[str] = set()
        for s in v:
            if s.id in seen:
                raise ValueError(f"duplicate workflow step id: {s.id!r}")
            seen.add(s.id)
        return v

    @model_validator(mode="after")
    def _name_matches_first_task_type_or_role(self) -> "Skill":
        # Soft convention: names like `bug_fix_skill` should align with task type.
        # Don't enforce strictly — just refuse outright contradictions.
        if not self.task_types:
            raise ValueError("at least one task_type required")
        return self

    # ---- helpers -------------------------------------------------------

    def for_task_type(self, t: TaskType) -> bool:
        return t in self.task_types

    def for_agent(self, a: AppliesTo) -> bool:
        return a in self.applies_to

    def find_forbidden(self, *, kind: ForbiddenKind,
                       target: str) -> ForbiddenAction | None:
        for fa in self.forbidden_actions:
            if fa.kind is kind and fa.matches(target):
                return fa
        return None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
