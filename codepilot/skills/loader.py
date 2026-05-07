"""YAML → Skill loader. Pure parse + Pydantic validation."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from codepilot.skills.base import Skill


class SkillParseError(ValueError):
    """Raised when a YAML file fails to parse or fails Skill validation."""


def load_skill_from_path(path: Path) -> Skill:
    raw = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise SkillParseError(f"YAML parse error in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SkillParseError(f"{path}: top-level must be a mapping")
    return _build_skill(data, source=path)


def load_skill_from_mapping(data: dict[str, Any]) -> Skill:
    return _build_skill(data, source=None)


def _build_skill(data: dict[str, Any], *, source: Path | None) -> Skill:
    try:
        return Skill.model_validate(data)
    except ValidationError as exc:
        loc = f" in {source}" if source is not None else ""
        raise SkillParseError(f"invalid skill{loc}: {exc}") from exc
