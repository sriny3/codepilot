"""Shell command guard. Validates commands before execution."""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from codepilot.guardrails.base import ALLOWED, Decision, GuardResult

if TYPE_CHECKING:
    from codepilot.skills.base import Skill


@dataclass(frozen=True)
class ShellRule:
    name: str
    pattern: str
    decision: Decision
    reason: str
    use_regex: bool = False


# Rules evaluated in order; first match wins.
# Specific patterns before general ones (e.g. git push --force before git push).
_BUILTIN_RULES: tuple[ShellRule, ...] = (
    # ── BLOCK: hard blocks, no approval path ────────────────────────────────
    ShellRule(
        "fork_bomb",
        r":(\s*)\(\s*\)\s*\{",
        Decision.BLOCK,
        "fork bomb — exhausts process table",
        use_regex=True,
    ),
    ShellRule(
        "mkfs",
        "mkfs",
        Decision.BLOCK,
        "destructive filesystem format",
    ),
    ShellRule(
        "dd_dev_wipe",
        r"dd\s+if=.*of=/dev/",
        Decision.BLOCK,
        "raw disk overwrite",
        use_regex=True,
    ),
    ShellRule(
        "eval_subshell",
        r"eval\s+[\"'`$\(]",
        Decision.BLOCK,
        "shell command injection via eval",
        use_regex=True,
    ),
    # ── HITL: needs human approval before running ────────────────────────────
    ShellRule(
        "git_push_force",
        "git push --force",
        Decision.HITL,
        "force-push rewrites remote history",
    ),
    ShellRule(
        "git_push_force_f",
        "git push -f",
        Decision.HITL,
        "force-push rewrites remote history",
    ),
    ShellRule(
        "git_push",
        "git push",
        Decision.HITL,
        "remote write requires approval",
    ),
    ShellRule(
        "git_reset_hard",
        "git reset --hard",
        Decision.HITL,
        "destructive history rewrite",
    ),
    ShellRule(
        "rm_rf",
        "rm -rf",
        Decision.HITL,
        "recursive force delete",
    ),
    ShellRule(
        "curl_net",
        "curl ",
        Decision.HITL,
        "network download",
    ),
    ShellRule(
        "wget_net",
        "wget ",
        Decision.HITL,
        "network download",
    ),
    # pip install -r / -e are lock-file paths; bare package installs are not.
    ShellRule(
        "pip_install_adhoc",
        r"pip\s+install\s+[^-]",
        Decision.HITL,
        "ad-hoc package install — use lock-file workflow instead",
        use_regex=True,
    ),
    ShellRule(
        "apt_get_install",
        "apt-get install",
        Decision.HITL,
        "system package install",
    ),
    ShellRule(
        "apt_install",
        "apt install",
        Decision.HITL,
        "system package install",
    ),
    ShellRule(
        "brew_install",
        "brew install",
        Decision.HITL,
        "system package install",
    ),
    ShellRule(
        "npm_install_adhoc",
        r"npm\s+install\s+[^-\.]",
        Decision.HITL,
        "ad-hoc npm package install",
        use_regex=True,
    ),
    ShellRule(
        "chmod_world",
        "chmod 777",
        Decision.HITL,
        "world-writable permissions",
    ),
    ShellRule(
        "sudo",
        "sudo ",
        Decision.HITL,
        "privilege escalation",
    ),
)


class ShellGuard:
    """Validates shell command strings against a deny / HITL rule table.

    Built-in rules are always evaluated first; caller-supplied `extra_rules`
    are appended (evaluated after built-ins if no built-in fired).
    """

    def __init__(self, extra_rules: Sequence[ShellRule] | None = None) -> None:
        self._rules: tuple[ShellRule, ...] = _BUILTIN_RULES + tuple(extra_rules or ())

    def validate(self, cmd: str) -> GuardResult:
        """Return the first matching rule's result, or ALLOWED."""
        for rule in self._rules:
            if rule.use_regex:
                if re.search(rule.pattern, cmd, re.IGNORECASE):
                    return GuardResult(
                        decision=rule.decision,
                        rule=rule.name,
                        reason=rule.reason,
                    )
            elif rule.pattern.lower() in cmd.lower():
                return GuardResult(
                    decision=rule.decision,
                    rule=rule.name,
                    reason=rule.reason,
                )
        return ALLOWED

    @classmethod
    def from_skill(cls, skill: "Skill") -> "ShellGuard":
        """Build a guard pre-loaded with the skill's SHELL forbidden_actions."""
        from codepilot.skills.base import ForbiddenKind

        extra = [
            ShellRule(
                name=f"skill:{fa.pattern[:30]}",
                pattern=fa.pattern,
                decision=Decision.BLOCK,
                reason=fa.reason,
            )
            for fa in skill.forbidden_actions
            if fa.kind is ForbiddenKind.SHELL
        ]
        return cls(extra_rules=extra)
