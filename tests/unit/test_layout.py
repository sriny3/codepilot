"""Smoke tests verifying the package layout from Phase 0 is intact."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "codepilot"

EXPECTED_SUBPACKAGES = [
    "orchestrator",
    "agents",
    "agents/repo_explorer",
    "agents/coder",
    "agents/test_agent",
    "agents/pr_agent",
    "skills",
    "memory",
    "guardrails",
    "tui",
    "sandbox",
    "github_io",
    "config",
    "observability",
]


@pytest.mark.parametrize("sub", EXPECTED_SUBPACKAGES)
def test_subpackage_exists(sub: str) -> None:
    init = PKG / sub / "__init__.py"
    assert init.exists(), f"missing {init}"


def test_pyproject_present() -> None:
    assert (ROOT / "pyproject.toml").exists()


def test_env_example_present() -> None:
    assert (ROOT / ".env.example").exists()


def test_makefile_or_tasks_present() -> None:
    assert (ROOT / "Makefile").exists() or (ROOT / "tasks.py").exists()
