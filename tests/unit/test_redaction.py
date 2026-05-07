import pytest

from codepilot.observability.redaction import REDACTED, redact


class TestSecretKeys:
    @pytest.mark.parametrize("key", [
        "github_token", "openai_api_key", "anthropic_api_key",
        "authorization", "api_key", "token", "password", "secret",
    ])
    def test_secret_key_value_redacted(self, key: str) -> None:
        out = redact({key: "anything-at-all"})
        assert out[key] == REDACTED

    def test_case_insensitive_key(self) -> None:
        assert redact({"Authorization": "Bearer abc"})["Authorization"] == REDACTED


class TestPatternScrubbing:
    @pytest.mark.parametrize("raw", [
        "ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "github_pat_BBBBBBBBBBBBBBBBBBBBBBBB",
        "sk-CCCCCCCCCCCCCCCCCCCCCCCC",
        "sk-ant-DDDDDDDDDDDDDDDDDDDDDDDD",
        "AKIAEEEEEEEEEEEEEEEE",
        "Bearer abc.def.ghi",
    ])
    def test_pattern_in_string(self, raw: str) -> None:
        msg = f"prefix {raw} suffix"
        assert REDACTED in redact(msg)
        assert raw not in redact(msg)


class TestStructure:
    def test_nested_dict(self) -> None:
        payload = {"outer": {"github_token": "ghp_xx"}}
        out = redact(payload)
        assert out["outer"]["github_token"] == REDACTED

    def test_list_of_strings(self) -> None:
        out = redact(["GITHUB_TOKEN=ghp_AAAAAAAAAAAAAAAAAAAAAA", "ok"])
        assert REDACTED in out[0]
        assert out[1] == "ok"

    def test_non_string_passthrough(self) -> None:
        assert redact({"n": 42, "f": 3.14, "b": True})["n"] == 42

    def test_pure_does_not_mutate(self) -> None:
        original = {"github_token": "ghp_xxxxxxxxxxxxxxxxxxxxxx"}
        snapshot = dict(original)
        redact(original)
        assert original == snapshot
