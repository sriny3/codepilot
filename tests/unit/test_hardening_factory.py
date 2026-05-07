"""Tests for PipelineConfig settings-driven factory."""
import pytest

from codepilot.agents.test_agent.runner import RunConfig
from codepilot.orchestrator.factory import PipelineConfig


class TestPipelineConfig:
    def test_direct_construction(self) -> None:
        cfg = PipelineConfig(run_config=RunConfig(command="pytest -x"))
        assert cfg.run_config.command == "pytest -x"

    def test_default_max_retries(self) -> None:
        cfg = PipelineConfig(run_config=RunConfig(command="pytest"))
        assert cfg.max_retries == 3

    def test_default_token_budget(self) -> None:
        cfg = PipelineConfig(run_config=RunConfig(command="pytest"))
        assert cfg.token_budget_repomap == 4000

    def test_default_tui_max_log_lines(self) -> None:
        cfg = PipelineConfig(run_config=RunConfig(command="pytest"))
        assert cfg.tui_max_log_lines == 1000


class TestPipelineConfigFromSettings:
    def test_from_settings_uses_max_retries(self, min_env: None) -> None:
        from codepilot.config.settings import Settings

        s = Settings()  # type: ignore[call-arg]
        cfg = PipelineConfig.from_settings(s)
        assert cfg.max_retries == s.max_retries

    def test_from_settings_uses_token_budget(self, min_env: None) -> None:
        from codepilot.config.settings import Settings

        s = Settings()  # type: ignore[call-arg]
        cfg = PipelineConfig.from_settings(s)
        assert cfg.token_budget_repomap == s.token_budget_repomap

    def test_from_settings_uses_test_command(self, min_env: None) -> None:
        from codepilot.config.settings import Settings

        s = Settings()  # type: ignore[call-arg]
        cfg = PipelineConfig.from_settings(s)
        assert cfg.run_config.command == s.test_command

    def test_from_settings_uses_test_timeout(self, min_env: None) -> None:
        from codepilot.config.settings import Settings

        s = Settings()  # type: ignore[call-arg]
        cfg = PipelineConfig.from_settings(s)
        assert cfg.run_config.timeout == s.test_timeout_s

    def test_from_settings_uses_tui_max_log_lines(self, min_env: None) -> None:
        from codepilot.config.settings import Settings

        s = Settings()  # type: ignore[call-arg]
        cfg = PipelineConfig.from_settings(s)
        assert cfg.tui_max_log_lines == s.tui_max_log_lines

    def test_from_settings_custom_command(
        self, min_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from codepilot.config.settings import Settings

        monkeypatch.setenv("TEST_COMMAND", "pytest tests/ -x")
        s = Settings()  # type: ignore[call-arg]
        cfg = PipelineConfig.from_settings(s)
        assert cfg.run_config.command == "pytest tests/ -x"
