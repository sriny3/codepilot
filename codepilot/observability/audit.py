"""Append-only audit log. fsync per write. Schema-validated. Daily rotation at UTC midnight."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from codepilot.observability.context import (
    current_issue_id,
    current_repo,
    current_trace_id,
)
from codepilot.observability.events import (
    AUDIT_ENVELOPE_SCHEMA,
    DETAIL_SCHEMAS,
)
from codepilot.observability.redaction import redact

_envelope_validator = Draft202012Validator(AUDIT_ENVELOPE_SCHEMA)


class AuditLog:
    """Append-only JSONL writer. fsync after every line.

    One instance per process is the norm. Tests instantiate per-test.
    """

    def __init__(self, log_dir: Path | str) -> None:
        self._dir = Path(log_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._current_date: str | None = None
        self._fp: Any = None

    def _path_for(self, date_utc: str) -> Path:
        return self._dir / f"audit-{date_utc}.jsonl"

    def _rotate_if_needed(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._current_date:
            if self._fp is not None:
                self._fp.flush()
                self._fp.close()
            self._fp = self._path_for(today).open("a", encoding="utf-8", buffering=1)
            self._current_date = today

    def write(
        self,
        event: str,
        details: dict[str, Any],
        *,
        actor: str = "orchestrator",
        ts: str | None = None,
        trace_id: str | None = None,
        issue_id: int | None = None,
        repo: str | None = None,
    ) -> dict[str, Any]:
        envelope = {
            "ts": ts or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "trace_id": trace_id or current_trace_id() or "",
            "issue_id": issue_id if issue_id is not None else current_issue_id(),
            "repo": repo or current_repo(),
            "event": event,
            "actor": actor,
            "details": redact(details),
        }
        if not envelope["trace_id"]:
            raise ValueError("audit.write: trace_id missing — bind_task() must wrap the call")

        _envelope_validator.validate(envelope)
        detail_schema = DETAIL_SCHEMAS.get(event)
        if detail_schema is not None:
            Draft202012Validator(detail_schema).validate(envelope["details"])

        line = json.dumps(envelope, sort_keys=True, ensure_ascii=False)

        with self._lock:
            self._rotate_if_needed()
            assert self._fp is not None
            self._fp.write(line + "\n")
            self._fp.flush()
            try:
                os.fsync(self._fp.fileno())
            except OSError:
                pass

        return envelope

    def close(self) -> None:
        with self._lock:
            if self._fp is not None:
                self._fp.close()
                self._fp = None
                self._current_date = None
