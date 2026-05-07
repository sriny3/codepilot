"""Shared types for the guardrails subsystem."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Decision(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"  # hard block — operation forbidden, no approval path
    HITL = "hitl"    # soft block — needs human approval before proceeding


@dataclass(frozen=True)
class GuardResult:
    decision: Decision
    rule: str    # triggering rule name; empty string when ALLOW
    reason: str  # human-readable explanation

    @property
    def is_allowed(self) -> bool:
        return self.decision is Decision.ALLOW

    @property
    def needs_hitl(self) -> bool:
        return self.decision is Decision.HITL

    @property
    def is_blocked(self) -> bool:
        return self.decision is Decision.BLOCK


# Singleton for the common-case clean pass — avoids allocating a new object per call.
ALLOWED = GuardResult(decision=Decision.ALLOW, rule="", reason="")
