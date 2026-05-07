import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError

from codepilot.observability.audit import AuditLog
from codepilot.observability.context import bind_task
from codepilot.observability.events import Event


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _read(audit_dir: Path) -> list[dict]:
    p = audit_dir / f"audit-{_today()}.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


class TestEnvelope:
    def test_required_fields_present(self, tmp_path: Path) -> None:
        log = AuditLog(tmp_path)
        with bind_task(42, repo="acme/x"):
            env = log.write(
                Event.ISSUE_PICKED_UP,
                {"issue_id": 42, "title": "Bug", "labels": ["ai-assignable"]},
            )
        log.close()
        for k in ("ts", "trace_id", "issue_id", "repo", "event", "actor", "details"):
            assert k in env
        assert env["repo"] == "acme/x"
        assert env["issue_id"] == 42

    def test_missing_trace_id_raises(self, tmp_path: Path) -> None:
        log = AuditLog(tmp_path)
        with pytest.raises(ValueError, match="trace_id"):
            log.write(Event.ISSUE_PICKED_UP,
                      {"issue_id": 1, "title": "x", "labels": []})


class TestSchemaValidation:
    def test_pr_opened_missing_required(self, tmp_path: Path) -> None:
        log = AuditLog(tmp_path)
        with bind_task(1):
            with pytest.raises(ValidationError):
                log.write(Event.PR_OPENED, {"pr_number": 7})  # missing url, base, head

    def test_hitl_decision_invalid_enum(self, tmp_path: Path) -> None:
        log = AuditLog(tmp_path)
        with bind_task(1):
            with pytest.raises(ValidationError):
                log.write(Event.HITL_DECISION,
                          {"decision": "maybe", "approver_login": "alice"})

    def test_unknown_event_passes_envelope(self, tmp_path: Path) -> None:
        # Unknown events still validated as envelope but no detail check.
        log = AuditLog(tmp_path)
        with bind_task(1):
            log.write("custom.event", {"foo": "bar"})
        rows = _read(tmp_path)
        assert rows[-1]["event"] == "custom.event"


class TestApproverCapture:
    def test_pr_opened_carries_approver(self, tmp_path: Path) -> None:
        log = AuditLog(tmp_path)
        with bind_task(99, repo="acme/x"):
            log.write(Event.HITL_DECISION, {
                "decision": "approve", "approver_login": "alice", "reason": "lgtm",
                "latency_ms": 1200,
            })
            log.write(Event.PR_OPENED, {
                "pr_number": 7, "url": "https://github.com/acme/x/pull/7",
                "base": "main", "head": "codepilot/issue-99-fix",
                "reviewer": "alice", "labels": ["codepilot-generated"],
                "approver_login": "alice",
            })
        rows = _read(tmp_path)
        decision = next(r for r in rows if r["event"] == Event.HITL_DECISION)
        opened = next(r for r in rows if r["event"] == Event.PR_OPENED)
        assert decision["details"]["approver_login"] == "alice"
        assert opened["details"]["approver_login"] == "alice"


class TestRedactionInDetails:
    def test_secret_in_details_scrubbed(self, tmp_path: Path) -> None:
        log = AuditLog(tmp_path)
        with bind_task(1):
            log.write("custom.event", {"github_token": "ghp_xxxxxxxxxxxxxxxxxxxxx"})
        rows = _read(tmp_path)
        assert rows[-1]["details"]["github_token"] == "***REDACTED***"


class TestAppendOnlyOrdering:
    def test_lines_in_write_order(self, tmp_path: Path) -> None:
        log = AuditLog(tmp_path)
        with bind_task(1):
            for i in range(5):
                log.write("custom.event", {"i": i})
                time.sleep(0.001)
        rows = _read(tmp_path)
        assert [r["details"]["i"] for r in rows[-5:]] == [0, 1, 2, 3, 4]


class TestRotation:
    def test_path_per_day(self, tmp_path: Path) -> None:
        log = AuditLog(tmp_path)
        with bind_task(1):
            log.write("custom.event", {"x": 1})
        log.close()
        files = list(tmp_path.glob("audit-*.jsonl"))
        assert len(files) == 1
        assert _today() in files[0].name
