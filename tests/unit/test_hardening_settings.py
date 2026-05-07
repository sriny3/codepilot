"""Tests for new settings fields added in Phase 13."""
import pytest

from codepilot.config.settings import Settings


class TestNewSettingsFields:
    def test_test_command_default(self, min_env: None) -> None:
        s = Settings()  # type: ignore[call-arg]
        assert s.test_command == "pytest"

    def test_test_timeout_s_default(self, min_env: None) -> None:
        s = Settings()  # type: ignore[call-arg]
        assert s.test_timeout_s == 120.0

    def test_tui_max_log_lines_default(self, min_env: None) -> None:
        s = Settings()  # type: ignore[call-arg]
        assert s.tui_max_log_lines == 1000

    def test_test_command_override(self, min_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_COMMAND", "pytest -x --tb=short")
        s = Settings()  # type: ignore[call-arg]
        assert s.test_command == "pytest -x --tb=short"

    def test_test_timeout_s_override(self, min_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_TIMEOUT_S", "60.0")
        s = Settings()  # type: ignore[call-arg]
        assert s.test_timeout_s == 60.0

    def test_tui_max_log_lines_override(
        self, min_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TUI_MAX_LOG_LINES", "500")
        s = Settings()  # type: ignore[call-arg]
        assert s.tui_max_log_lines == 500

    def test_test_timeout_s_minimum_enforced(
        self, min_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pydantic import ValidationError

        monkeypatch.setenv("TEST_TIMEOUT_S", "1.0")
        with pytest.raises(ValidationError):
            Settings()  # type: ignore[call-arg]
