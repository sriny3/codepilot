from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    github_app_id: str
    github_app_private_key: str
    github_token: SecretStr | None = None           # optional, backwards compat
    repo_full_name: str = Field(pattern=r"^[\w.-]+/[\w.-]+$")

    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None

    poll_interval_min: int = Field(default=5, ge=1, le=120)
    max_retries: int = Field(default=3, ge=1, le=10)
    token_budget_repomap: int = Field(default=4000, ge=500, le=32000)
    complexity_threshold: int = Field(default=6, ge=1, le=10)
    max_inflight_tasks: int = Field(default=2, ge=1, le=20)
    test_command: str = Field(default="pytest")
    test_timeout_s: float = Field(default=120.0, ge=5.0, le=3600.0)
    tui_max_log_lines: int = Field(default=1000, ge=10, le=100000)

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_dir: Path = Path("./logs")
    log_format: Literal["json", "console"] = "json"
    otel_exporter_otlp_endpoint: str | None = None
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "codepilot"

    @field_validator("log_dir", mode="before")
    @classmethod
    def _coerce_log_dir(cls, v: object) -> Path:
        return Path(str(v)) if not isinstance(v, Path) else v

    @model_validator(mode="after")
    def _require_one_llm_key(self) -> "Settings":
        if not (self.openai_api_key or self.anthropic_api_key):
            raise ValueError(
                "at least one of OPENAI_API_KEY or ANTHROPIC_API_KEY must be set"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
