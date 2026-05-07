"""Skill → system prompt rendering. Stable, deterministic, redaction-safe."""
from __future__ import annotations

from codepilot.skills.base import Skill

_SECTION_BAR = "═" * 60
_SUB_BAR = "─" * 60


def to_system_prompt(skill: Skill, *, include_examples: bool = True) -> str:
    """Render a skill into a system prompt block injectable into a subagent.

    Output is stable for a given skill version — useful for prompt cache keys.
    """
    parts: list[str] = []
    parts.append(_SECTION_BAR)
    parts.append(f"SKILL: {skill.name}  v{skill.version}")
    parts.append(_SECTION_BAR)
    parts.append(f"Description: {skill.description}")
    parts.append(f"Task types: {', '.join(t.value for t in skill.task_types)}")
    parts.append(f"Applies to: {', '.join(a.value for a in skill.applies_to)}")
    if skill.owner:
        parts.append(f"Owner: {skill.owner}")
    parts.append("")

    parts.append("INSTRUCTIONS")
    parts.append(_SUB_BAR)
    parts.append(skill.instructions.strip())
    parts.append("")

    parts.append("WORKFLOW")
    parts.append(_SUB_BAR)
    for i, step in enumerate(skill.workflow_steps, 1):
        parts.append(f"{i}. {step.title}  [id={step.id}]")
        for line in step.instructions.strip().splitlines():
            parts.append(f"   {line}")
        if step.success_criteria:
            parts.append(f"   ✓ {step.success_criteria}")
    parts.append("")

    if skill.checklist:
        parts.append("CHECKLIST")
        parts.append(_SUB_BAR)
        for item in skill.checklist:
            parts.append(f"  [ ] {item}")
        parts.append("")

    if skill.forbidden_actions:
        parts.append("FORBIDDEN ACTIONS")
        parts.append(_SUB_BAR)
        parts.append(
            "If you need any of the following, REQUEST HUMAN APPROVAL — do not execute."
        )
        for fa in skill.forbidden_actions:
            parts.append(f"  - [{fa.kind.value}] {fa.pattern}  -- {fa.reason}")
        parts.append("")

    if include_examples and skill.example_prompts:
        parts.append("EXAMPLE PROMPTS")
        parts.append(_SUB_BAR)
        for ex in skill.example_prompts:
            parts.append(f"  • {ex.prompt}")
            if ex.expected_workflow:
                parts.append(
                    f"      expected steps: {' → '.join(ex.expected_workflow)}"
                )
        parts.append("")

    if skill.references:
        parts.append("REFERENCES")
        parts.append(_SUB_BAR)
        for r in skill.references:
            parts.append(f"  - {r}")
        parts.append("")

    parts.append(_SECTION_BAR)
    return "\n".join(parts).rstrip() + "\n"
