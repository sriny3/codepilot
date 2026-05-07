import pytest
from pydantic import ValidationError

from codepilot.skills.base import (
    AppliesTo,
    ForbiddenAction,
    ForbiddenKind,
    Skill,
    SkillExample,
    TaskType,
    WorkflowStep,
)


def _wf(id: str = "step", title: str = "do thing",
        instructions: str = "do it") -> WorkflowStep:
    return WorkflowStep(id=id, title=title, instructions=instructions)


def _skill(**kw) -> Skill:
    base = dict(
        name="bug_fix",
        description="Fix bugs.",
        task_types=(TaskType.BUG_FIX,),
        applies_to=(AppliesTo.CODER,),
        instructions="reproduce, localize, fix",
        workflow_steps=(_wf(),),
    )
    base.update(kw)
    return Skill(**base)


class TestWorkflowStep:
    def test_valid(self) -> None:
        s = WorkflowStep(id="reproduce", title="Repro", instructions="...")
        assert s.id == "reproduce"

    @pytest.mark.parametrize("bad_id", ["", "Reproduce", "1step", "step-with-dash",
                                        "step with space"])
    def test_invalid_id_pattern(self, bad_id: str) -> None:
        with pytest.raises(ValidationError):
            WorkflowStep(id=bad_id, title="t", instructions="i")

    def test_empty_title_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WorkflowStep(id="ok", title="", instructions="i")


class TestForbiddenAction:
    def test_shell_substring_match(self) -> None:
        fa = ForbiddenAction(kind=ForbiddenKind.SHELL, pattern="rm -rf",
                             reason="destructive")
        assert fa.matches("sudo rm -rf /tmp") is True
        assert fa.matches("ls") is False

    def test_shell_match_case_insensitive(self) -> None:
        fa = ForbiddenAction(kind=ForbiddenKind.SHELL, pattern="PIP install",
                             reason="x")
        assert fa.matches("pip Install foo") is True

    def test_file_glob_match(self) -> None:
        fa = ForbiddenAction(kind=ForbiddenKind.FILE, pattern="*.env",
                             reason="secret")
        assert fa.matches(".env") is True
        assert fa.matches("config/.env") is True
        assert fa.matches("env.txt") is False

    def test_regex_match(self) -> None:
        fa = ForbiddenAction(kind=ForbiddenKind.REGEX,
                             pattern=r"ghp_[A-Za-z0-9]{20,}",
                             reason="github pat")
        assert fa.matches("token=ghp_AAAAAAAAAAAAAAAAAAAA") is True
        assert fa.matches("just text") is False


class TestSkillSchema:
    def test_minimal_valid(self) -> None:
        s = _skill()
        assert s.name == "bug_fix"
        assert s.version == 1
        assert s.applies_to == (AppliesTo.CODER,)

    @pytest.mark.parametrize("bad", ["", "Bug-Fix", "1bug", "bug fix"])
    def test_bad_name_rejected(self, bad: str) -> None:
        with pytest.raises(ValidationError):
            _skill(name=bad)

    def test_empty_task_types_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _skill(task_types=())

    def test_empty_workflow_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _skill(workflow_steps=())

    def test_duplicate_step_ids_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _skill(workflow_steps=(_wf("a"), _wf("a")))

    def test_immutable(self) -> None:
        s = _skill()
        with pytest.raises(ValidationError):
            s.name = "other"  # type: ignore[misc]

    def test_negative_version_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _skill(version=0)


class TestForTaskTypeAndAgent:
    def test_for_task_type_match(self) -> None:
        s = _skill(task_types=(TaskType.BUG_FIX, TaskType.DOCUMENTATION))
        assert s.for_task_type(TaskType.BUG_FIX)
        assert s.for_task_type(TaskType.DOCUMENTATION)
        assert not s.for_task_type(TaskType.FEATURE_ADDITION)

    def test_for_agent_match(self) -> None:
        s = _skill(applies_to=(AppliesTo.CODER, AppliesTo.EXPLORER))
        assert s.for_agent(AppliesTo.CODER)
        assert s.for_agent(AppliesTo.EXPLORER)
        assert not s.for_agent(AppliesTo.PR_AGENT)


class TestFindForbidden:
    def test_match_by_kind(self) -> None:
        s = _skill(forbidden_actions=(
            ForbiddenAction(kind=ForbiddenKind.SHELL, pattern="rm -rf",
                            reason="x"),
            ForbiddenAction(kind=ForbiddenKind.FILE, pattern="*.env",
                            reason="y"),
        ))
        assert s.find_forbidden(kind=ForbiddenKind.SHELL,
                                target="rm -rf /") is not None
        assert s.find_forbidden(kind=ForbiddenKind.FILE,
                                target="config/.env") is not None
        assert s.find_forbidden(kind=ForbiddenKind.SHELL,
                                target="ls") is None
        assert s.find_forbidden(kind=ForbiddenKind.FILE,
                                target="src/x.py") is None
