import json
from pathlib import Path

import pytest

from codepilot.observability import logger as log_mod
from codepilot.observability.context import bind_span, bind_task


@pytest.fixture(autouse=True)
def _reset() -> None:
    log_mod.reset_for_tests()
    yield
    log_mod.reset_for_tests()


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


class TestLoggerFields:
    def test_trace_and_span_present(self, tmp_path: Path) -> None:
        log_mod.configure(level="INFO", log_dir=tmp_path, log_format="json")
        log = log_mod.get_logger("test")
        with bind_task(42, repo="acme/x"):
            with bind_span("step"):
                log.info("hello", extra_field="x")

        files = list(tmp_path.glob("*.jsonl"))
        assert files
        rows = _read_jsonl(files[0])
        rec = rows[-1]
        assert rec["event"] == "hello"
        assert rec["trace_id"]
        assert rec["span_id"]
        assert rec["issue_id"] == 42
        assert rec["repo"] == "acme/x"
        assert rec["extra_field"] == "x"


class TestRedactionInLogs:
    def test_secret_value_scrubbed(self, tmp_path: Path) -> None:
        log_mod.configure(level="INFO", log_dir=tmp_path, log_format="json")
        log = log_mod.get_logger("test")
        with bind_task(1):
            log.info("authing", github_token="ghp_AAAAAAAAAAAAAAAAAAAA")

        rec = _read_jsonl(next(tmp_path.glob("*.jsonl")))[-1]
        assert rec["github_token"] == "***REDACTED***"

    def test_inline_pattern_scrubbed(self, tmp_path: Path) -> None:
        log_mod.configure(level="INFO", log_dir=tmp_path, log_format="json")
        log = log_mod.get_logger("test")
        with bind_task(1):
            log.info("token=ghp_AAAAAAAAAAAAAAAAAAAAAA found")

        rec = _read_jsonl(next(tmp_path.glob("*.jsonl")))[-1]
        assert "ghp_" not in rec["event"]
        assert "REDACTED" in rec["event"]


class TestIdempotentConfigure:
    def test_double_configure_safe(self, tmp_path: Path) -> None:
        log_mod.configure(log_dir=tmp_path)
        log_mod.configure(log_dir=tmp_path)
        log_mod.get_logger("x").info("ping")
        assert list(tmp_path.glob("*.jsonl"))


class TestLogLevels:
    def test_debug_filtered_at_info(self, tmp_path: Path) -> None:
        log_mod.configure(level="INFO", log_dir=tmp_path, log_format="json")
        log = log_mod.get_logger("test")
        with bind_task(1):
            log.debug("hidden")
            log.info("visible")

        rows = _read_jsonl(next(tmp_path.glob("*.jsonl")))
        msgs = [r["event"] for r in rows]
        assert "visible" in msgs
        assert "hidden" not in msgs
