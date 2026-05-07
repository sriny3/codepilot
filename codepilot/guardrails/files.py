"""File path guard. Validates paths before read/write operations."""
from __future__ import annotations

import fnmatch
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from codepilot.guardrails.base import ALLOWED, Decision, GuardResult

if TYPE_CHECKING:
    from codepilot.skills.base import Skill


@dataclass(frozen=True)
class FileRule:
    name: str
    pattern: str   # fnmatch glob checked against full path and/or basename
    decision: Decision
    reason: str
    match_full_path: bool = True
    match_basename: bool = True


_BUILTIN_RULES: tuple[FileRule, ...] = (
    # env files — cover .env, config.env, .env.local, .env.production, etc.
    FileRule("dotenv_star",    "*.env",          Decision.BLOCK, "environment secrets file"),
    FileRule("dotenv_local",   ".env.*",         Decision.BLOCK, "environment secrets file variant"),
    # TLS / PKI
    FileRule("pem_cert",       "*.pem",          Decision.BLOCK, "TLS certificate or private key"),
    FileRule("private_key",    "*.key",          Decision.BLOCK, "private key file"),
    FileRule("pfx_cert",       "*.pfx",          Decision.BLOCK, "PKCS#12 certificate bundle"),
    FileRule("p12_cert",       "*.p12",          Decision.BLOCK, "PKCS#12 certificate bundle"),
    # Secret / credential files
    FileRule("secret_file",    "*.secret",       Decision.BLOCK, "generic secret file"),
    FileRule("credentials",    "*credentials*",  Decision.BLOCK, "credentials file"),
    # SSH keys
    FileRule("id_rsa",         "*id_rsa*",       Decision.BLOCK, "RSA private key"),
    FileRule("id_ed25519",     "*id_ed25519*",   Decision.BLOCK, "ED25519 private key"),
    FileRule("id_dsa",         "*id_dsa*",       Decision.BLOCK, "DSA private key"),
    FileRule("id_ecdsa",       "*id_ecdsa*",     Decision.BLOCK, "ECDSA private key"),
    # Network / tool credential stores
    FileRule("netrc",          ".netrc",         Decision.BLOCK, "netrc contains plaintext credentials"),
    # Git internals that may carry auth tokens
    FileRule("git_config",     ".git/config",    Decision.BLOCK, "git config may contain auth tokens",
             match_full_path=True, match_basename=False),
)


class FileGuard:
    """Validates file paths against a deny rule list.

    Each rule pattern is checked against:
    - the full path (when `rule.match_full_path` is True)
    - the basename only (when `rule.match_basename` is True)

    First-match wins. `fnmatch.fnmatch` is used for glob expansion; `*`
    matches path separators in Python's fnmatch, so `*.pem` matches both
    `cert.pem` and `certs/server.pem`.
    """

    def __init__(self, extra_rules: Sequence[FileRule] | None = None) -> None:
        self._rules: tuple[FileRule, ...] = _BUILTIN_RULES + tuple(extra_rules or ())

    def validate_path(self, path: str) -> GuardResult:
        """Return the first matching rule's result, or ALLOWED."""
        basename = os.path.basename(path)
        for rule in self._rules:
            if rule.match_full_path and fnmatch.fnmatch(path, rule.pattern):
                return GuardResult(
                    decision=rule.decision,
                    rule=rule.name,
                    reason=rule.reason,
                )
            if rule.match_basename and fnmatch.fnmatch(basename, rule.pattern):
                return GuardResult(
                    decision=rule.decision,
                    rule=rule.name,
                    reason=rule.reason,
                )
        return ALLOWED

    @classmethod
    def from_skill(cls, skill: "Skill") -> "FileGuard":
        """Build a guard pre-loaded with the skill's FILE forbidden_actions."""
        from codepilot.skills.base import ForbiddenKind

        extra = [
            FileRule(
                name=f"skill:{fa.pattern[:30]}",
                pattern=fa.pattern,
                decision=Decision.BLOCK,
                reason=fa.reason,
            )
            for fa in skill.forbidden_actions
            if fa.kind is ForbiddenKind.FILE
        ]
        return cls(extra_rules=extra)
