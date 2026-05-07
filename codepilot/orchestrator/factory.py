"""Settings-driven pipeline configuration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from codepilot.agents.test_agent.runner import RunConfig

if TYPE_CHECKING:
    from codepilot.config.settings import Settings


@dataclass
class PipelineConfig:
    """All settings-derived values for one pipeline run.

    Decouples the Orchestrator and agents from the Settings object so
    they remain testable without environment variables.
    """

    run_config: RunConfig
    max_retries: int = 3
    token_budget_repomap: int = 4000
    tui_max_log_lines: int = 1000

    @classmethod
    def from_settings(cls, settings: "Settings") -> "PipelineConfig":
        return cls(
            run_config=RunConfig(
                command=settings.test_command,
                timeout=settings.test_timeout_s,
            ),
            max_retries=settings.max_retries,
            token_budget_repomap=settings.token_budget_repomap,
            tui_max_log_lines=settings.tui_max_log_lines,
        )
