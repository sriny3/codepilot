from codepilot.skills.base import (
    AppliesTo,
    ForbiddenAction,
    ForbiddenKind,
    Skill,
    SkillExample,
    TaskType,
    WorkflowStep,
)
from codepilot.skills.render import to_system_prompt


def _full_skill() -> Skill:
    return Skill(
        name="bug_fix",
        version=2,
        description="Fix bugs.",
        task_types=(TaskType.BUG_FIX,),
        applies_to=(AppliesTo.CODER,),
        owner="platform-agents",
        instructions="reproduce, localize, fix",
        workflow_steps=(
            WorkflowStep(id="reproduce", title="Repro",
                         instructions="write failing test",
                         success_criteria="test fails"),
            WorkflowStep(id="fix", title="Fix",
                         instructions="apply minimal change"),
        ),
        example_prompts=(
            SkillExample(prompt="Fix null in user lookup",
                         expected_workflow=["reproduce", "fix"]),
        ),
        forbidden_actions=(
            ForbiddenAction(kind=ForbiddenKind.SHELL, pattern="rm -rf",
                            reason="destructive"),
        ),
        checklist=("Did you write a failing test first?",),
        references=("https://example.com/bug-fix-howto",),
    )


class TestRenderSections:
    def test_includes_skill_header(self) -> None:
        out = to_system_prompt(_full_skill())
        assert "SKILL: bug_fix" in out
        assert "v2" in out
        assert "Owner: platform-agents" in out

    def test_includes_instructions(self) -> None:
        out = to_system_prompt(_full_skill())
        assert "INSTRUCTIONS" in out
        assert "reproduce, localize, fix" in out

    def test_includes_workflow_in_order(self) -> None:
        out = to_system_prompt(_full_skill())
        assert "WORKFLOW" in out
        assert out.index("[id=reproduce]") < out.index("[id=fix]")
        assert "[id=reproduce]" in out
        assert "[id=fix]" in out

    def test_success_criteria_rendered(self) -> None:
        out = to_system_prompt(_full_skill())
        assert "✓ test fails" in out

    def test_includes_checklist(self) -> None:
        out = to_system_prompt(_full_skill())
        assert "CHECKLIST" in out
        assert "Did you write a failing test first?" in out

    def test_includes_forbidden(self) -> None:
        out = to_system_prompt(_full_skill())
        assert "FORBIDDEN ACTIONS" in out
        assert "rm -rf" in out
        assert "destructive" in out
        assert "REQUEST HUMAN APPROVAL" in out

    def test_includes_examples_by_default(self) -> None:
        out = to_system_prompt(_full_skill())
        assert "EXAMPLE PROMPTS" in out
        assert "Fix null in user lookup" in out

    def test_examples_omitted_when_disabled(self) -> None:
        out = to_system_prompt(_full_skill(), include_examples=False)
        assert "EXAMPLE PROMPTS" not in out

    def test_references_section(self) -> None:
        out = to_system_prompt(_full_skill())
        assert "REFERENCES" in out
        assert "example.com/bug-fix-howto" in out


class TestRenderStability:
    def test_deterministic(self) -> None:
        s = _full_skill()
        assert to_system_prompt(s) == to_system_prompt(s)


class TestMinimalSkill:
    def test_optional_sections_omitted(self) -> None:
        s = Skill(
            name="x",
            description="d",
            task_types=(TaskType.BUG_FIX,),
            instructions="i",
            workflow_steps=(WorkflowStep(id="a", title="A", instructions="i"),),
        )
        out = to_system_prompt(s)
        assert "CHECKLIST" not in out
        assert "FORBIDDEN ACTIONS" not in out
        assert "EXAMPLE PROMPTS" not in out
        assert "REFERENCES" not in out
