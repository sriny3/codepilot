"""Lifecycle event taxonomy. Single source of truth for event names + audit schema."""
from __future__ import annotations

from typing import Final


class Event:
    ISSUE_PICKED_UP:    Final = "issue.picked_up"
    ISSUE_CLASSIFIED:   Final = "issue.classified"
    TODOS_WRITTEN:      Final = "todos.written"
    REPO_MAP_BUILT:     Final = "repo_map.built"
    FILES_RETRIEVED:    Final = "files.retrieved"
    EDIT_APPLIED:       Final = "edit.applied"
    SANDBOX_EXECUTE:    Final = "sandbox.execute"
    TESTS_RUN:          Final = "tests.run"
    GUARDRAIL_BLOCK:    Final = "guardrail.block"
    HITL_REQUESTED:     Final = "hitl.requested"
    HITL_DECISION:      Final = "hitl.decision"
    BRANCH_CREATED:     Final = "branch.created"
    COMMIT_CREATED:     Final = "commit.created"
    PR_OPENED:          Final = "pr.opened"
    STATE_TRANSITION:   Final = "state.transition"
    TASK_COMPLETE:      Final = "task.complete"


# Subset of events that MUST be persisted to the append-only audit log.
AUDIT_EVENTS: frozenset[str] = frozenset({
    Event.ISSUE_PICKED_UP,
    Event.GUARDRAIL_BLOCK,
    Event.HITL_REQUESTED,
    Event.HITL_DECISION,
    Event.BRANCH_CREATED,
    Event.COMMIT_CREATED,
    Event.PR_OPENED,
    Event.TASK_COMPLETE,
})


# JSONSchema for audit envelope. Per-event detail schemas in DETAIL_SCHEMAS.
AUDIT_ENVELOPE_SCHEMA: dict = {
    "type": "object",
    "required": ["ts", "trace_id", "event", "actor", "details"],
    "properties": {
        "ts":        {"type": "string", "format": "date-time"},
        "trace_id":  {"type": "string", "minLength": 1},
        "issue_id":  {"type": ["integer", "null"]},
        "repo":      {"type": ["string", "null"]},
        "event":     {"type": "string"},
        "actor":     {"type": "string", "minLength": 1},
        "details":   {"type": "object"},
    },
    "additionalProperties": True,
}


DETAIL_SCHEMAS: dict[str, dict] = {
    Event.ISSUE_PICKED_UP: {
        "type": "object",
        "required": ["issue_id", "title", "labels"],
        "properties": {
            "issue_id": {"type": "integer"},
            "title":    {"type": "string"},
            "labels":   {"type": "array", "items": {"type": "string"}},
            "reporter": {"type": ["string", "null"]},
        },
    },
    Event.GUARDRAIL_BLOCK: {
        "type": "object",
        "required": ["rule", "operation", "agent"],
        "properties": {
            "rule":      {"type": "string"},
            "operation": {"type": "string"},
            "agent":     {"type": "string"},
        },
    },
    Event.HITL_REQUESTED: {
        "type": "object",
        "required": ["operation"],
        "properties": {
            "operation":       {"type": "string"},
            "context_summary": {"type": "string"},
        },
    },
    Event.HITL_DECISION: {
        "type": "object",
        "required": ["decision", "approver_login"],
        "properties": {
            "decision":       {"type": "string", "enum": ["approve", "reject"]},
            "approver_login": {"type": "string", "minLength": 1},
            "reason":         {"type": ["string", "null"]},
            "latency_ms":     {"type": ["integer", "null"]},
        },
    },
    Event.BRANCH_CREATED: {
        "type": "object",
        "required": ["branch_name", "base_sha"],
        "properties": {
            "branch_name": {"type": "string"},
            "base_sha":    {"type": "string"},
        },
    },
    Event.COMMIT_CREATED: {
        "type": "object",
        "required": ["sha", "files_changed"],
        "properties": {
            "sha":           {"type": "string"},
            "files_changed": {"type": "integer"},
        },
    },
    Event.PR_OPENED: {
        "type": "object",
        "required": ["pr_number", "url", "base", "head"],
        "properties": {
            "pr_number":      {"type": "integer"},
            "url":            {"type": "string"},
            "base":           {"type": "string"},
            "head":           {"type": "string"},
            "reviewer":       {"type": ["string", "null"]},
            "labels":         {"type": "array", "items": {"type": "string"}},
            "approver_login": {"type": ["string", "null"]},
        },
    },
    Event.TASK_COMPLETE: {
        "type": "object",
        "required": ["outcome", "duration_ms"],
        "properties": {
            "outcome":     {"type": "string", "enum": ["DONE", "FAILED"]},
            "duration_ms": {"type": "integer"},
        },
    },
}
