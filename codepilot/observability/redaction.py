"""Strip secrets from log payloads before they reach disk.

Applied as a structlog processor and reused by the audit log.
"""
from __future__ import annotations

import re
from typing import Any

REDACTED = "***REDACTED***"

# Field names whose value is always a secret.
SECRET_KEYS = frozenset({
    "github_token", "github_app_private_key", "openai_api_key", "anthropic_api_key",
    "qdrant_api_key", "langsmith_api_key", "authorization", "api_key", "token",
    "password", "secret",
})

# Heuristic patterns. Conservative — false positives are fine, false negatives are not.
PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-(?:ant-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)authorization:\s*\S+"),
)


def _scrub_str(s: str) -> str:
    out = s
    for pat in PATTERNS:
        out = pat.sub(REDACTED, out)
    return out


def redact(value: Any) -> Any:
    """Recursively redact a payload. Pure — does not mutate input."""
    if isinstance(value, str):
        return _scrub_str(value)
    if isinstance(value, dict):
        return {
            k: REDACTED if k.lower() in SECRET_KEYS else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, tuple):
        return tuple(redact(v) for v in value)
    return value


def structlog_redactor(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """structlog processor signature."""
    return redact(event_dict)


def redact_cmd(cmd: str, max_len: int = 200) -> str:
    """Redact secrets from a shell command string and truncate for logging."""
    scrubbed = _scrub_str(cmd)
    if len(scrubbed) > max_len:
        return scrubbed[:max_len] + "…"
    return scrubbed
