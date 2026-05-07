"""Prompt injection detection for untrusted text (e.g. GitHub issue bodies).

Uses compiled regex patterns as the default backend.  When nemoguardrails is
installed a NeMo-backed subclass can be substituted without changing call sites.
"""
from __future__ import annotations

import re

from codepilot.guardrails.base import ALLOWED, Decision, GuardResult

# Each tuple is (compiled_pattern, rule_name).
_INJECTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+instructions?"),
        "ignore_instructions",
    ),
    (
        re.compile(r"(?i)you\s+are\s+now\s+(a\s+|an\s+)?"),
        "role_override",
    ),
    (
        re.compile(r"(?i)(act|behave)\s+as\s+(a\s+|an\s+)?"),
        "persona_hijack",
    ),
    (
        re.compile(r"(?im)^system\s*:\s*$"),
        "fake_system_prompt",
    ),
    (
        re.compile(r"(?i)new\s+system\s+prompt"),
        "system_prompt_override",
    ),
    (
        re.compile(r"\n\n(Human|User)\s*:"),
        "chat_format_injection",
    ),
    (
        re.compile(r"\n\n(Assistant|AI)\s*:"),
        "chat_format_injection",
    ),
    (
        re.compile(r"(?i)(jailbreak|DAN\s+mode|developer\s+mode)"),
        "jailbreak_keyword",
    ),
    (
        re.compile(r"(?i)disregard\s+your\s+(previous|prior|original)"),
        "disregard_override",
    ),
    (
        re.compile(r"(?i)forget\s+(everything|all)\s+you\s+(know|were\s+told)"),
        "forget_override",
    ),
    (
        re.compile(r"\{\{.*?\}\}", re.DOTALL),
        "template_injection",
    ),
    (
        re.compile(r"\{%.*?%\}", re.DOTALL),
        "template_tag_injection",
    ),
    (
        re.compile(r"(?i)<\s*/?INST\s*>"),
        "llama_inst_injection",
    ),
    (
        re.compile(r"(?i)\[SYSTEM\]"),
        "bracket_system_injection",
    ),
]


class PromptGuard:
    """Detects prompt injection in untrusted text.

    validate_text returns ALLOWED or a BLOCK result with the triggering rule.
    Designed to be called on GitHub issue bodies before they are forwarded to
    any LLM.
    """

    def validate_text(self, text: str) -> GuardResult:
        for pattern, name in _INJECTION_PATTERNS:
            if pattern.search(text):
                return GuardResult(
                    decision=Decision.BLOCK,
                    rule=name,
                    reason="potential prompt injection detected",
                )
        return ALLOWED
