from pathlib import Path

import pytest

from codepilot.skills.base import (
    AppliesTo,
    Skill,
    TaskType,
    WorkflowStep,
)
from codepilot.skills.registry import (
    DEFAULT_DEFINITIONS_DIR,
    SkillNotFound,
    SkillsRegistry,
)


def _yaml(name: str, *, task_types: list[str] = ["bug_fix"],
          applies_to: list[str] = ["coder"], version: int = 1) -> str:
    tt = "\n".join(f"  - {t}" for t in task_types)
    at = "\n".join(f"  - {a}" for a in applies_to)
    return (
        f"name: {name}\n"
        f"version: {version}\n"
        f"description: {name} desc\n"
        f"task_types:\n{tt}\n"
        f"applies_to:\n{at}\n"
        f"instructions: do thing\n"
        f"workflow_steps:\n"
        f"  - id: a\n    title: A\n    instructions: i\n"
    )


def _build(tmp_path: Path, files: dict[str, str]) -> Path:
    d = tmp_path / "defs"
    d.mkdir()
    for name, body in files.items():
        (d / name).write_text(body, encoding="utf-8")
    return d


class TestDefaultDefinitions:
    def test_loads_all_four_shipped_skills(self) -> None:
        r = SkillsRegistry()
        assert set(r.names()) == {
            "bug_fix", "feature_addition",
            "dependency_update", "documentation",
        }

    def test_default_dir_resolves(self) -> None:
        assert DEFAULT_DEFINITIONS_DIR.exists()


class TestCustomDir:
    def test_loads_only_from_custom_dir(self, tmp_path: Path) -> None:
        d = _build(tmp_path, {"x.yaml": _yaml("x")})
        r = SkillsRegistry(definitions_dirs=[d])
        assert r.names() == ["x"]

    def test_duplicate_names_logged_and_kept_first(self, tmp_path: Path) -> None:
        d = _build(tmp_path, {
            "a.yaml": _yaml("dup"),
            "b.yaml": _yaml("dup"),
        })
        r = SkillsRegistry(definitions_dirs=[d])
        assert "dup" in r
        assert len(r) == 1


class TestLoadAndGet:
    def test_load_returns_skill(self, tmp_path: Path) -> None:
        d = _build(tmp_path, {"x.yaml": _yaml("x")})
        r = SkillsRegistry(definitions_dirs=[d])
        s = r.load("x")
        assert isinstance(s, Skill)

    def test_load_missing_raises(self, tmp_path: Path) -> None:
        d = _build(tmp_path, {"x.yaml": _yaml("x")})
        r = SkillsRegistry(definitions_dirs=[d])
        with pytest.raises(SkillNotFound):
            r.load("missing")

    def test_get_missing_returns_default(self, tmp_path: Path) -> None:
        d = _build(tmp_path, {"x.yaml": _yaml("x")})
        r = SkillsRegistry(definitions_dirs=[d])
        assert r.get("missing") is None
        assert r.get("missing", "fallback") == "fallback"  # type: ignore[arg-type]


class TestSelection:
    def test_for_task_type(self, tmp_path: Path) -> None:
        d = _build(tmp_path, {
            "a.yaml": _yaml("a", task_types=["bug_fix"]),
            "b.yaml": _yaml("b", task_types=["bug_fix", "documentation"]),
            "c.yaml": _yaml("c", task_types=["documentation"]),
        })
        r = SkillsRegistry(definitions_dirs=[d])
        bug = r.for_task_type(TaskType.BUG_FIX)
        assert {s.name for s in bug} == {"a", "b"}

    def test_select_prefers_more_specific(self, tmp_path: Path) -> None:
        d = _build(tmp_path, {
            "narrow.yaml": _yaml("narrow", task_types=["bug_fix"]),
            "wide.yaml": _yaml("wide", task_types=["bug_fix", "documentation"]),
        })
        r = SkillsRegistry(definitions_dirs=[d])
        chosen = r.select(task_type=TaskType.BUG_FIX)
        assert chosen.name == "narrow"

    def test_select_filters_by_agent(self, tmp_path: Path) -> None:
        d = _build(tmp_path, {
            "a.yaml": _yaml("a", applies_to=["coder"]),
            "b.yaml": _yaml("b", applies_to=["explorer"]),
        })
        r = SkillsRegistry(definitions_dirs=[d])
        s = r.select(task_type=TaskType.BUG_FIX, agent=AppliesTo.EXPLORER)
        assert s.name == "b"

    def test_select_no_match_raises(self, tmp_path: Path) -> None:
        d = _build(tmp_path, {"a.yaml": _yaml("a", task_types=["bug_fix"])})
        r = SkillsRegistry(definitions_dirs=[d])
        with pytest.raises(SkillNotFound):
            r.select(task_type=TaskType.FEATURE_ADDITION)


class TestDynamicRegistration:
    def test_register_and_load(self, tmp_path: Path) -> None:
        d = _build(tmp_path, {})
        r = SkillsRegistry(definitions_dirs=[d])
        custom = Skill(
            name="custom",
            description="d", task_types=(TaskType.BUG_FIX,),
            instructions="i",
            workflow_steps=(WorkflowStep(id="a", title="A", instructions="i"),),
        )
        r.register(custom)
        assert r.load("custom") is custom


class TestReload:
    def test_picks_up_new_files(self, tmp_path: Path) -> None:
        d = _build(tmp_path, {"a.yaml": _yaml("a")})
        r = SkillsRegistry(definitions_dirs=[d])
        assert r.names() == ["a"]
        (d / "b.yaml").write_text(_yaml("b"), encoding="utf-8")
        r.reload()
        assert set(r.names()) == {"a", "b"}

    def test_drops_deleted_files(self, tmp_path: Path) -> None:
        d = _build(tmp_path, {"a.yaml": _yaml("a"), "b.yaml": _yaml("b")})
        r = SkillsRegistry(definitions_dirs=[d])
        (d / "b.yaml").unlink()
        r.reload()
        assert r.names() == ["a"]


class TestErrorHandling:
    def test_bad_file_does_not_break_others(self, tmp_path: Path) -> None:
        d = _build(tmp_path, {
            "good.yaml": _yaml("good"),
            "bad.yaml": "name: bad\ndescription: x\ntask_types: []\n"
                        "instructions: i\nworkflow_steps: []\n",
        })
        r = SkillsRegistry(definitions_dirs=[d])
        # Bad file dropped; good still loaded.
        assert r.names() == ["good"]
