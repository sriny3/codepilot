"""End-to-end: write a full task lifecycle, reconstruct via trace CLI."""
import json
from pathlib import Path

import pytest

from codepilot.observability import logger as log_mod
from codepilot.observability.audit import AuditLog
from codepilot.observability.context import bind_span, bind_state, bind_task
from codepilot.observability.events import Event
from codepilot.observability.trace_cli import collect, main


@pytest.fixture(autouse=True)
def _reset() -> None:
    log_mod.reset_for_tests()
    yield
    log_mod.reset_for_tests()


def _full_lifecycle(log_dir: Path) -> str:
    """Simulate pickup → classify → plan → explore → code → test → HITL → PR → done."""
    log_mod.configure(level="INFO", log_dir=log_dir, log_format="json")
    audit = AuditLog(log_dir)
    structured = log_mod.get_logger("orchestrator")

    with bind_task(42, repo="acme/x") as tid:
        audit.write(Event.ISSUE_PICKED_UP,
                    {"issue_id": 42, "title": "Null pointer", "labels": ["bug"],
                     "reporter": "bob"})
        with bind_state("TRIAGED"):
            structured.info(Event.ISSUE_CLASSIFIED, task_type="bug_fix", confidence=0.9)
        with bind_state("EXPLORING"), bind_span("explore", "explorer"):
            structured.info(Event.REPO_MAP_BUILT, files_count=120, tokens_used=3800)
            structured.info(Event.FILES_RETRIEVED, strategy="keyword",
                            top_k=8, paths=["src/a.py", "src/b.py"])
        with bind_state("IMPLEMENTING"), bind_span("code", "coder"):
            structured.info(Event.EDIT_APPLIED, file="src/a.py", added=3, removed=1)
        with bind_state("TESTING"), bind_span("test", "tester"):
            structured.info(Event.TESTS_RUN, passed=12, failed=0, framework="pytest")
        audit.write(Event.HITL_REQUESTED,
                    {"operation": "open PR to main", "context_summary": "5 files"})
        audit.write(Event.HITL_DECISION,
                    {"decision": "approve", "approver_login": "alice",
                     "reason": "lgtm", "latency_ms": 4200})
        audit.write(Event.BRANCH_CREATED,
                    {"branch_name": "codepilot/issue-42-fix", "base_sha": "deadbeef"})
        audit.write(Event.COMMIT_CREATED, {"sha": "abc123", "files_changed": 2})
        audit.write(Event.PR_OPENED, {
            "pr_number": 7, "url": "https://github.com/acme/x/pull/7",
            "base": "main", "head": "codepilot/issue-42-fix",
            "reviewer": "bob", "labels": ["codepilot-generated"],
            "approver_login": "alice",
        })
        with bind_state("DONE"):
            audit.write(Event.TASK_COMPLETE,
                        {"outcome": "DONE", "duration_ms": 92000})

    audit.close()
    return tid


class TestReconstruction:
    def test_collect_returns_full_timeline(self, tmp_path: Path) -> None:
        tid = _full_lifecycle(tmp_path)
        rows = collect(tmp_path, tid)
        events = [r.get("event") for r in rows]
        for required in [
            Event.ISSUE_PICKED_UP,
            Event.ISSUE_CLASSIFIED,
            Event.REPO_MAP_BUILT,
            Event.FILES_RETRIEVED,
            Event.EDIT_APPLIED,
            Event.TESTS_RUN,
            Event.HITL_REQUESTED,
            Event.HITL_DECISION,
            Event.BRANCH_CREATED,
            Event.COMMIT_CREATED,
            Event.PR_OPENED,
            Event.TASK_COMPLETE,
        ]:
            assert required in events, f"missing {required}"

    def test_rows_sorted_by_timestamp(self, tmp_path: Path) -> None:
        tid = _full_lifecycle(tmp_path)
        rows = collect(tmp_path, tid)
        ts_values = [r["ts"] for r in rows]
        assert ts_values == sorted(ts_values)

    def test_approver_recovered_from_audit(self, tmp_path: Path) -> None:
        tid = _full_lifecycle(tmp_path)
        rows = collect(tmp_path, tid)
        pr = next(r for r in rows if r.get("event") == Event.PR_OPENED)
        assert pr["details"]["approver_login"] == "alice"

    def test_other_traces_excluded(self, tmp_path: Path) -> None:
        tid_a = _full_lifecycle(tmp_path)
        # second task w/ different trace
        log_mod.reset_for_tests()
        log_mod.configure(level="INFO", log_dir=tmp_path, log_format="json")
        with bind_task(99, repo="acme/y"):
            log_mod.get_logger().info("noise")

        rows = collect(tmp_path, tid_a)
        for r in rows:
            assert r["trace_id"] == tid_a


class TestCLI:
    def test_known_trace_returns_zero(self, tmp_path: Path,
                                      capsys: pytest.CaptureFixture[str]) -> None:
        tid = _full_lifecycle(tmp_path)
        rc = main([tid, "--log-dir", str(tmp_path)])
        out = capsys.readouterr().out
        assert rc == 0
        assert Event.PR_OPENED in out
        assert Event.ISSUE_PICKED_UP in out

    def test_unknown_trace_returns_one(self, tmp_path: Path,
                                       capsys: pytest.CaptureFixture[str]) -> None:
        _full_lifecycle(tmp_path)
        rc = main(["nonexistent-trace", "--log-dir", str(tmp_path)])
        assert rc == 1

    def test_json_output(self, tmp_path: Path,
                         capsys: pytest.CaptureFixture[str]) -> None:
        tid = _full_lifecycle(tmp_path)
        main([tid, "--log-dir", str(tmp_path), "--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, list)
        assert len(data) >= 12
