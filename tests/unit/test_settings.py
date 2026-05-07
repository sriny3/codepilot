from pathlib import Path

import pytest
from pydantic import ValidationError

from codepilot.config.settings import Settings, get_settings


class TestRequiredFields:
    def test_loads_from_env(self, min_env: None) -> None:
        s = Settings()  # type: ignore[call-arg]
        assert s.github_app_id == "12345"
        assert s.github_app_private_key == "fake-key"
        assert s.repo_full_name == "acme/widgets"
        assert s.openai_api_key is not None

    def test_missing_github_app_id_raises(self, clean_env: None,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "fake-key")
        monkeypatch.setenv("REPO_FULL_NAME", "acme/widgets")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        with pytest.raises(ValidationError):
            Settings()  # type: ignore[call-arg]

    def test_missing_github_app_private_key_raises(self, clean_env: None,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_APP_ID", "12345")
        monkeypatch.setenv("REPO_FULL_NAME", "acme/widgets")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        with pytest.raises(ValidationError):
            Settings()  # type: ignore[call-arg]

    def test_github_token_optional(self, clean_env: None,
                                   monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_APP_ID", "12345")
        monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "fake-key")
        monkeypatch.setenv("REPO_FULL_NAME", "acme/widgets")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        s = Settings()  # type: ignore[call-arg]
        assert s.github_token is None
        assert s.github_app_id == "12345"

    def test_missing_repo_full_name_raises(self, clean_env: None,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_APP_ID", "12345")
        monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "fake-key")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        with pytest.raises(ValidationError):
            Settings()  # type: ignore[call-arg]

    def test_invalid_repo_name_format(self, clean_env: None,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_APP_ID", "12345")
        monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "fake-key")
        monkeypatch.setenv("REPO_FULL_NAME", "not-a-valid-repo")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        with pytest.raises(ValidationError):
            Settings()  # type: ignore[call-arg]


class TestLLMKeyRequirement:
    def test_neither_llm_key_raises(self, clean_env: None,
                                    monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_APP_ID", "12345")
        monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "fake-key")
        monkeypatch.setenv("REPO_FULL_NAME", "acme/widgets")
        with pytest.raises(ValidationError):
            Settings()  # type: ignore[call-arg]

    def test_only_anthropic_key_ok(self, clean_env: None,
                                   monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_APP_ID", "12345")
        monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "fake-key")
        monkeypatch.setenv("REPO_FULL_NAME", "acme/widgets")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        s = Settings()  # type: ignore[call-arg]
        assert s.anthropic_api_key is not None
        assert s.openai_api_key is None


class TestDefaults:
    def test_defaults_applied(self, min_env: None) -> None:
        s = Settings()  # type: ignore[call-arg]
        assert s.poll_interval_min == 5
        assert s.max_retries == 3
        assert s.token_budget_repomap == 4000
        assert s.complexity_threshold == 6
        assert s.max_inflight_tasks == 2
        assert s.qdrant_url == "http://localhost:6333"
        assert s.log_level == "INFO"
        assert s.log_format == "json"
        assert s.langsmith_project == "codepilot"

    def test_log_dir_coerced_to_path(self, min_env: None,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_DIR", "/tmp/cp")
        s = Settings()  # type: ignore[call-arg]
        assert isinstance(s.log_dir, Path)
        assert str(s.log_dir).replace("\\", "/") == "/tmp/cp"


class TestBoundsValidation:
    @pytest.mark.parametrize("var,value", [
        ("POLL_INTERVAL_MIN", "0"),
        ("POLL_INTERVAL_MIN", "121"),
        ("MAX_RETRIES", "0"),
        ("MAX_RETRIES", "11"),
        ("TOKEN_BUDGET_REPOMAP", "100"),
        ("TOKEN_BUDGET_REPOMAP", "100000"),
        ("COMPLEXITY_THRESHOLD", "0"),
        ("COMPLEXITY_THRESHOLD", "11"),
    ])
    def test_out_of_bounds_raises(self, min_env: None,
                                  monkeypatch: pytest.MonkeyPatch,
                                  var: str, value: str) -> None:
        monkeypatch.setenv(var, value)
        with pytest.raises(ValidationError):
            Settings()  # type: ignore[call-arg]

    def test_invalid_log_level_raises(self, min_env: None,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_LEVEL", "TRACE")
        with pytest.raises(ValidationError):
            Settings()  # type: ignore[call-arg]

    def test_invalid_log_format_raises(self, min_env: None,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_FORMAT", "xml")
        with pytest.raises(ValidationError):
            Settings()  # type: ignore[call-arg]


class TestSecretHandling:
    def test_secrets_not_in_repr(self, min_env: None) -> None:
        s = Settings()  # type: ignore[call-arg]
        assert "ghp_test" not in repr(s)
        assert "sk-test" not in repr(s)


class TestCachedAccessor:
    def test_get_settings_cached(self, min_env: None) -> None:
        get_settings.cache_clear()
        a = get_settings()
        b = get_settings()
        assert a is b
        get_settings.cache_clear()
