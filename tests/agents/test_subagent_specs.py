"""Tests for subagent spec TypedDicts."""
from __future__ import annotations

import pytest


_REQUIRED_KEYS = {"name", "description", "system_prompt", "tools", "permissions"}
_SUBAGENT_NAMES = ["REPO_EXPLORER", "CODER", "TEST_AGENT", "PR_AGENT"]


@pytest.mark.parametrize("spec_name", _SUBAGENT_NAMES)
def test_subagent_has_required_keys(spec_name: str) -> None:
    import codepilot.agents.subagents as subagents_module

    spec = getattr(subagents_module, spec_name)
    for key in _REQUIRED_KEYS:
        assert key in spec, f"{spec_name} missing key {key!r}"


@pytest.mark.parametrize("spec_name", _SUBAGENT_NAMES)
def test_subagent_name_is_string(spec_name: str) -> None:
    import codepilot.agents.subagents as subagents_module

    spec = getattr(subagents_module, spec_name)
    assert isinstance(spec["name"], str)
    assert len(spec["name"]) > 0


@pytest.mark.parametrize("spec_name", _SUBAGENT_NAMES)
def test_subagent_tools_is_list(spec_name: str) -> None:
    import codepilot.agents.subagents as subagents_module

    spec = getattr(subagents_module, spec_name)
    assert isinstance(spec["tools"], list)


@pytest.mark.parametrize("spec_name", _SUBAGENT_NAMES)
def test_subagent_permissions_is_list(spec_name: str) -> None:
    import codepilot.agents.subagents as subagents_module

    spec = getattr(subagents_module, spec_name)
    assert isinstance(spec["permissions"], list)
    assert len(spec["permissions"]) > 0


def test_all_subagents_collected() -> None:
    from codepilot.agents.subagents import ALL_SUBAGENTS

    assert len(ALL_SUBAGENTS) == 4
    names = {s["name"] for s in ALL_SUBAGENTS}
    assert names == {"repo_explorer", "coder", "test_agent", "pr_agent"}
