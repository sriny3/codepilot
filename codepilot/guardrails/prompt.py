"""Prompt injection detection for untrusted text (e.g. GitHub issue bodies).

Uses compiled regex patterns as the default backend.  When nemoguardrails is
installed a NeMo-backed subclass can be substituted without changing call sites.
"""
from __future__ import annotations

import importlib.util as _ilu
import re

_NEMO_AVAILABLE: bool = _ilu.find_spec("nemoguardrails") is not None

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


class NemoPromptGuard(PromptGuard):
    """Uses NeMo Guardrails when available; falls back to regex patterns."""

    def __init__(self) -> None:
        self._rails = None  # lazy init

    def _get_rails(self):
        if self._rails is None:
            from nemoguardrails import RailsConfig  # type: ignore[import]
            from nemoguardrails.integrations.langchain.runnable_rails import RunnableRails  # type: ignore[import]
            config = RailsConfig.from_content(
                yaml_content="""
models: []
rails:
  input:
    flows:
      - check jailbreak
      - check input sensitive data
"""
            )
            self._rails = RunnableRails(config=config)
        return self._rails

    def _nemo_validate(self, text: str) -> GuardResult:
        rails = self._get_rails()
        output = rails.invoke({"input": text})
        # Check structured output first, then fall back to string inspection
        if isinstance(output, dict) and output.get("blocked"):
            return GuardResult(
                decision=Decision.BLOCK,
                rule="nemo_rails",
                reason="NeMo Guardrails blocked input",
            )
        out_str = str(output).lower()
        if "blocked" in out_str or "not allowed" in out_str or "i am not able" in out_str:
            return GuardResult(
                decision=Decision.BLOCK,
                rule="nemo_rails",
                reason="NeMo Guardrails blocked input",
            )
        return ALLOWED

    def validate_text(self, text: str) -> GuardResult:
        if _NEMO_AVAILABLE:
            try:
                return self._nemo_validate(text)
            except Exception:
                pass
        return super().validate_text(text)


def make_prompt_guard() -> PromptGuard:
    """Return NemoPromptGuard if nemoguardrails is installed, else PromptGuard."""
    if _NEMO_AVAILABLE:
        return NemoPromptGuard()
    return PromptGuard()
