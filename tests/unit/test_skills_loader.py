from pathlib import Path

import pytest

from codepilot.skills.base import TaskType
from codepilot.skills.loader import (
    SkillParseError,
    load_skill_from_mapping,
    load_skill_from_path,
)


_VALID_DICT = {
    "name": "demo",
    "version": 2,
    "description": "demo skill",
    "task_types": ["bug_fix"],
    "applies_to": ["coder"],
    "instructions": "do the thing",
    "workflow_steps": [
        {"id": "step1", "title": "Step", "instructions": "step instructions"},
    ],
}


class TestLoadFromMapping:
    def test_valid(self) -> None:
        s = load_skill_from_mapping(_VALID_DICT)
        assert s.name == "demo"
        assert s.version == 2
        assert s.task_types == (TaskType.BUG_FIX,)

    def test_invalid_raises_skill_parse_error(self) -> None:
        bad = {**_VALID_DICT, "task_types": []}
        with pytest.raises(SkillParseError):
            load_skill_from_mapping(bad)


class TestLoadFromPath:
    def test_yaml_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "x.yaml"
        path.write_text(
            "name: x\n"
            "description: x\n"
            "task_types: [bug_fix]\n"
            "instructions: i\n"
            "workflow_steps:\n"
            "  - id: a\n"
            "    title: A\n"
            "    instructions: do A\n",
            encoding="utf-8",
        )
        s = load_skill_from_path(path)
        assert s.name == "x"

    def test_non_mapping_top_level_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "x.yaml"
        path.write_text("- list\n- of\n- things\n", encoding="utf-8")
        with pytest.raises(SkillParseError, match="must be a mapping"):
            load_skill_from_path(path)

    def test_invalid_yaml_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "x.yaml"
        path.write_text("name: x\ninvalid:::yaml\n  - tab\n", encoding="utf-8")
        with pytest.raises(SkillParseError):
            load_skill_from_path(path)
