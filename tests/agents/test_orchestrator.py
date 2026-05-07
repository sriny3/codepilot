"""Tests for build_orchestrator — mocks create_deep_agent."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestBuildOrchestrator:
    def test_returns_compiled_graph(self, min_env: None) -> None:
        mock_graph = MagicMock()
        mock_graph.invoke = MagicMock(return_value={"messages": []})
        mock_graph.stream = MagicMock(return_value=iter([]))

        with patch("codepilot.orchestrator.deep_agent.create_deep_agent", return_value=mock_graph):
            from codepilot.agents.test_agent.runner import RunConfig
            from codepilot.orchestrator.deep_agent import build_orchestrator
            from codepilot.orchestrator.factory import PipelineConfig

            cfg = PipelineConfig(run_config=RunConfig(command="pytest"))
            result = build_orchestrator(cfg)

        assert result is mock_graph

    def test_create_deep_agent_called_with_subagents(self, min_env: None) -> None:
        mock_graph = MagicMock()

        with patch(
            "codepilot.orchestrator.deep_agent.create_deep_agent", return_value=mock_graph
        ) as mock_create:
            from codepilot.agents.test_agent.runner import RunConfig
            from codepilot.orchestrator.deep_agent import build_orchestrator
            from codepilot.orchestrator.factory import PipelineConfig

            cfg = PipelineConfig(run_config=RunConfig(command="pytest"))
            build_orchestrator(cfg)

        call_kwargs = mock_create.call_args.kwargs
        assert "subagents" in call_kwargs
        assert len(call_kwargs["subagents"]) == 4

    def test_create_deep_agent_has_interrupt_on(self, min_env: None) -> None:
        mock_graph = MagicMock()

        with patch(
            "codepilot.orchestrator.deep_agent.create_deep_agent", return_value=mock_graph
        ) as mock_create:
            from codepilot.agents.test_agent.runner import RunConfig
            from codepilot.orchestrator.deep_agent import build_orchestrator
            from codepilot.orchestrator.factory import PipelineConfig

            cfg = PipelineConfig(run_config=RunConfig(command="pytest"))
            build_orchestrator(cfg)

        call_kwargs = mock_create.call_args.kwargs
        assert "interrupt_on" in call_kwargs
        interrupt = call_kwargs["interrupt_on"]
        assert interrupt.get("open_pr") is True
        assert interrupt.get("commit_files") is True

    def test_orchestrator_system_prompt_non_empty(self, min_env: None) -> None:
        mock_graph = MagicMock()

        with patch(
            "codepilot.orchestrator.deep_agent.create_deep_agent", return_value=mock_graph
        ) as mock_create:
            from codepilot.agents.test_agent.runner import RunConfig
            from codepilot.orchestrator.deep_agent import build_orchestrator
            from codepilot.orchestrator.factory import PipelineConfig

            cfg = PipelineConfig(run_config=RunConfig(command="pytest"))
            build_orchestrator(cfg)

        call_kwargs = mock_create.call_args.kwargs
        assert "system_prompt" in call_kwargs
        assert len(call_kwargs["system_prompt"]) > 100
