"""SkillsRegistry — discovers, caches, and serves Skill objects."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Iterable

from codepilot.observability import get_logger
from codepilot.skills.base import AppliesTo, Skill, TaskType
from codepilot.skills.loader import SkillParseError, load_skill_from_path

_log = get_logger("skills.registry")

DEFAULT_DEFINITIONS_DIR = Path(__file__).resolve().parent / "definitions"


class SkillNotFound(KeyError):
    pass


class SkillsRegistry:
    """In-process registry. Loads YAML definitions on construction.

    Thread-safe; tests can reset via `reload()`.
    """

    def __init__(
        self,
        *,
        definitions_dirs: Iterable[Path] | None = None,
        eager: bool = True,
    ) -> None:
        self._dirs: list[Path] = list(definitions_dirs) if definitions_dirs else [
            DEFAULT_DEFINITIONS_DIR,
        ]
        self._lock = threading.Lock()
        self._by_name: dict[str, Skill] = {}
        if eager:
            self.reload()

    # ---- discovery -----------------------------------------------------

    def reload(self) -> None:
        loaded: dict[str, Skill] = {}
        errors: list[str] = []
        for directory in self._dirs:
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.yaml")):
                try:
                    skill = load_skill_from_path(path)
                except SkillParseError as exc:
                    errors.append(str(exc))
                    continue
                if skill.name in loaded:
                    errors.append(
                        f"duplicate skill name {skill.name!r} (in {path})"
                    )
                    continue
                loaded[skill.name] = skill
        with self._lock:
            self._by_name = loaded
        _log.info(
            "skills.loaded",
            count=len(loaded),
            names=sorted(loaded),
            error_count=len(errors),
        )
        if errors:
            for e in errors:
                _log.error("skills.load_error", error=e)

    # ---- lookups -------------------------------------------------------

    def load(self, name: str) -> Skill:
        with self._lock:
            skill = self._by_name.get(name)
        if skill is None:
            raise SkillNotFound(name)
        return skill

    def get(self, name: str, default: Skill | None = None) -> Skill | None:
        with self._lock:
            return self._by_name.get(name, default)

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._by_name)

    def all(self) -> list[Skill]:
        with self._lock:
            return list(self._by_name.values())

    def __contains__(self, name: str) -> bool:
        with self._lock:
            return name in self._by_name

    def __len__(self) -> int:
        with self._lock:
            return len(self._by_name)

    # ---- selection -----------------------------------------------------

    def for_task_type(self, t: TaskType) -> list[Skill]:
        with self._lock:
            return [s for s in self._by_name.values() if s.for_task_type(t)]

    def select(self, *, task_type: TaskType,
               agent: AppliesTo | None = None) -> Skill:
        """Return the most specific skill matching `task_type` (and optionally agent).

        Tie-breaker: prefer skills with fewer task_types (more specific) and
        higher version. Raises SkillNotFound when nothing matches.
        """
        candidates = self.for_task_type(task_type)
        if agent is not None:
            candidates = [s for s in candidates if s.for_agent(agent)]
        if not candidates:
            raise SkillNotFound(
                f"no skill for task_type={task_type.value} agent="
                f"{agent.value if agent else 'any'}"
            )
        candidates.sort(key=lambda s: (len(s.task_types), -s.version, s.name))
        return candidates[0]

    # ---- registration (programmatic, for tests / dynamic skills) ------

    def register(self, skill: Skill) -> None:
        with self._lock:
            self._by_name[skill.name] = skill
