"""Smoke tests over the 4 skills shipped in `codepilot/skills/definitions/`."""
import pytest

from codepilot.skills.base import AppliesTo, ForbiddenKind, TaskType
from codepilot.skills.registry import SkillsRegistry
from codepilot.skills.render import to_system_prompt


@pytest.fixture(scope="module")
def registry() -> SkillsRegistry:
    return SkillsRegistry()


SHIPPED_NAMES = ["bug_fix", "feature_addition", "dependency_update", "documentation"]


@pytest.mark.parametrize("name", SHIPPED_NAMES)
def test_each_skill_loads(registry: SkillsRegistry, name: str) -> None:
    s = registry.load(name)
    assert s.name == name
    assert s.workflow_steps
    assert s.instructions.strip()


@pytest.mark.parametrize("name", SHIPPED_NAMES)
def test_each_skill_renders_nonempty(registry: SkillsRegistry, name: str) -> None:
    s = registry.load(name)
    out = to_system_prompt(s)
    assert "SKILL:" in out
    assert len(out) > 200


def test_each_task_type_has_a_default_skill(registry: SkillsRegistry) -> None:
    for t in [TaskType.BUG_FIX, TaskType.FEATURE_ADDITION,
              TaskType.DEPENDENCY_UPDATE, TaskType.DOCUMENTATION]:
        chosen = registry.select(task_type=t, agent=AppliesTo.CODER)
        assert chosen.for_task_type(t)


@pytest.mark.parametrize("name", SHIPPED_NAMES)
def test_secret_files_blocked(registry: SkillsRegistry, name: str) -> None:
    s = registry.load(name)
    # Documentation skill blocks .env via file kind too.
    if name == "feature_addition" or name == "documentation" or \
       name == "bug_fix" or name == "dependency_update":
        assert s.find_forbidden(kind=ForbiddenKind.FILE,
                                target=".env") is not None


def test_dependency_update_blocks_pip_install(registry: SkillsRegistry) -> None:
    s = registry.load("dependency_update")
    assert s.find_forbidden(kind=ForbiddenKind.SHELL,
                            target="pip install requests") is not None


def test_bug_fix_blocks_rm_rf(registry: SkillsRegistry) -> None:
    s = registry.load("bug_fix")
    assert s.find_forbidden(kind=ForbiddenKind.SHELL,
                            target="rm -rf /tmp/x") is not None


def test_documentation_blocks_pat_pattern(registry: SkillsRegistry) -> None:
    s = registry.load("documentation")
    fa = s.find_forbidden(
        kind=ForbiddenKind.REGEX,
        target="see token=ghp_AAAAAAAAAAAAAAAAAAAAA in setup",
    )
    assert fa is not None
