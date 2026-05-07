import os
from collections.abc import Iterator

import pytest


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Strip every CodePilot-relevant env var so tests start from a known empty state."""
    for k in list(os.environ):
        if k in {
            "GITHUB_TOKEN", "GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY",
            "REPO_FULL_NAME",
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
            "POLL_INTERVAL_MIN", "MAX_RETRIES", "TOKEN_BUDGET_REPOMAP",
            "COMPLEXITY_THRESHOLD", "MAX_INFLIGHT_TASKS",
            "QDRANT_URL", "QDRANT_API_KEY",
            "LOG_LEVEL", "LOG_DIR", "LOG_FORMAT",
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "LANGSMITH_API_KEY", "LANGSMITH_PROJECT",
        }:
            monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(os.getcwd())
    yield


@pytest.fixture
def min_env(monkeypatch: pytest.MonkeyPatch, clean_env: None) -> None:
    """Minimal valid env for Settings()."""
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "fake-key")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")   # optional, kept for backwards compat
    monkeypatch.setenv("REPO_FULL_NAME", "acme/widgets")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
