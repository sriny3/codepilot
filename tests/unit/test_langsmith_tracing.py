"""Unit tests for LangSmith tracing configuration."""
from __future__ import annotations

import os

import pytest

from codepilot.observability.langsmith_tracing import configure_langsmith, is_configured


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("LANGCHAIN_TRACING_V2", "LANGCHAIN_API_KEY", "LANGCHAIN_PROJECT", "LANGSMITH_API_KEY"):
        monkeypatch.delenv(key, raising=False)


def test_configure_sets_tracing_v2() -> None:
    configure_langsmith("lsv2_test_key")
    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"


def test_configure_sets_api_key() -> None:
    configure_langsmith("lsv2_test_key")
    assert os.environ["LANGCHAIN_API_KEY"] == "lsv2_test_key"
    assert os.environ["LANGSMITH_API_KEY"] == "lsv2_test_key"


def test_configure_sets_default_project() -> None:
    configure_langsmith("lsv2_test_key")
    assert os.environ["LANGCHAIN_PROJECT"] == "codepilot"


def test_configure_respects_custom_project() -> None:
    configure_langsmith("lsv2_test_key", project="my-project")
    assert os.environ["LANGCHAIN_PROJECT"] == "my-project"


def test_is_configured_false_before_setup() -> None:
    assert not is_configured()


def test_is_configured_true_after_setup() -> None:
    configure_langsmith("lsv2_test_key")
    assert is_configured()
