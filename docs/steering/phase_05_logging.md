# Phase 0.5 — Steering Doc: Logging & Tracing Foundation

**Status:** complete
**Owner:** platform / observability
**Depends on:** Phase 0 (Settings, package layout)
**Unblocks:** every phase from 1 onward — every component logs through this layer

---

## Goal

End-to-end traceability of one task: from the moment an issue is picked up through classify → plan → explore → code → test → HITL approval → branch → commit → PR open → done. Given a single `trace_id`, anyone must be able to grep both log streams and reconstruct what happened, who approved it, and when.

## Deliverables

| Artifact | Path | Purpose |
|---|---|---|
| Context vars | `codepilot/observability/context.py` | `trace_id`, `span_id`, `issue_id`, `repo`, `agent`, `state` propagated via `contextvars` |
| Redactor | `codepilot/observability/redaction.py` | strips secret keys + token patterns from any payload |
| Logger | `codepilot/observability/logger.py` | structlog → JSON file (rotated) + console; auto-binds context |
| Audit log | `codepilot/observability/audit.py` | append-only JSONL, fsync per write, JSONSchema-validated |
| Event taxonomy | `codepilot/observability/events.py` | single source of truth for event names + schemas |
| OTel | `codepilot/observability/tracing.py` | OTLP exporter wrapper; no-op without endpoint |
| Trace CLI | `codepilot/observability/trace_cli.py` | `python -m codepilot.observability.trace_cli <trace_id>` reconstructs timeline |
| Tests | `tests/unit/test_{context,redaction,logger,audit,tracing,trace_cli}.py` | 53 new tests |
| Doctor enhancement | `codepilot/__main__.py` | `doctor` now dumps resolved config (secrets masked) |

## Exit Criteria

- Any `trace_id` produced by `pr.opened` reconstructs full pickup→PR timeline via `trace_cli`.
- HITL approver login captured in `hitl.decision` AND propagated into `pr.opened` audit record AND into PR body footer (PR body wiring lands in Phase 9; the audit field is in place).
- Secrets never reach disk — verified for both structured logs and audit details.
- `pytest` green: 95 tests passing.

---

## Files

### Source

**`codepilot/observability/__init__.py`**
Public surface. Re-exports every callable other modules need (`bind_task`, `bind_span`, `bind_state`, `with_trace`, `get_logger`, `configure_logging`, `configure_tracing`, `start_span`, `AuditLog`, `Event`, `redact`, `reset_for_tests`). Callers import from `codepilot.observability` only — internal modules never imported directly.

**`codepilot/observability/context.py`**
Correlation-ID plumbing. Defines seven `ContextVar`s (`trace_id`, `span_id`, `parent_span_id`, `issue_id`, `repo`, `agent_name`, `state`). Public API:
- `bind_task(issue_id, repo=None, trace_id=None)` — context manager. Mints (or accepts) `trace_id` and pins it for the issue's lifetime. THE entry point at issue pickup.
- `bind_span(name, agent=None)` — opens new span, captures previous as `parent_span_id`. Nestable.
- `bind_state(state)` — sets state-machine label (`TRIAGED|EXPLORING|...`) on logs while held.
- `with_trace(name, agent=None)` decorator — wraps sync or async callable in a span. Detects coroutine fn via `asyncio.iscoroutinefunction`.
- `context_snapshot()` — flattens all set vars to a dict for log/span injection.
- `current_trace_id()`, `current_span_id()`, etc — read-only accessors.

**`codepilot/observability/redaction.py`**
Pure scrubber. Two layers: `SECRET_KEYS` set (matches dict keys case-insensitive: github_token, openai_api_key, etc) → replaces value with `***REDACTED***`. `PATTERNS` tuple of regexes (ghp_, github_pat_, sk-, sk-ant-, AIza, AKIA, xox*, `Bearer ...`, `Authorization: ...`) → scrubs inside any string. `redact(value)` recurses through dicts/lists/tuples; immutable inputs preserved (does not mutate). `structlog_redactor(logger, method, event_dict)` — adapter matching structlog processor signature.

**`codepilot/observability/logger.py`**
structlog setup. Module globals: `_CONFIGURED` flag for idempotency. `configure(level, log_dir, log_format, file_name)` builds the processor chain:
1. `merge_contextvars` (structlog's own ctx merge)
2. `add_log_level`
3. ISO UTC `TimeStamper`
4. `_ctx_processor` (injects `context_snapshot()` fields)
5. `structlog_redactor`
6. `StackInfoRenderer` + `format_exc_info`
7. Renderer — `JSONRenderer(sort_keys=True)` for prod, `ConsoleRenderer(colors=True)` for dev (selected via `log_format`).
Wires a `TimedRotatingFileHandler` (midnight UTC, 30 backups) when `log_dir` set. `get_logger(name)` lazy-configures if not already. `reset_for_tests()` clears module state and stdlib root handlers — tests use it as fixture cleanup.

**`codepilot/observability/events.py`**
Single source of truth. `class Event` with 16 `Final` constants (`ISSUE_PICKED_UP`, `ISSUE_CLASSIFIED`, `TODOS_WRITTEN`, `REPO_MAP_BUILT`, `FILES_RETRIEVED`, `EDIT_APPLIED`, `SANDBOX_EXECUTE`, `TESTS_RUN`, `GUARDRAIL_BLOCK`, `HITL_REQUESTED`, `HITL_DECISION`, `BRANCH_CREATED`, `COMMIT_CREATED`, `PR_OPENED`, `STATE_TRANSITION`, `TASK_COMPLETE`). `AUDIT_EVENTS` frozenset names which events MUST go to the audit log. `AUDIT_ENVELOPE_SCHEMA` JSONSchema for the wrapper. `DETAIL_SCHEMAS` dict — per-event JSONSchema for `details` field. Adding a new event = add constant + schema in one place.

**`codepilot/observability/audit.py`**
Append-only writer. `AuditLog(log_dir)` instance per process. Thread-safe via `threading.Lock`. `write(event, details, *, actor, ts, trace_id, issue_id, repo)`:
1. Builds envelope from explicit args + context fallbacks.
2. Raises `ValueError` if `trace_id` empty (forces `bind_task` discipline).
3. Validates envelope against `AUDIT_ENVELOPE_SCHEMA`; if event has a `DETAIL_SCHEMAS` entry, validates details too.
4. Redacts details before write.
5. Rotates file at UTC midnight (`audit-YYYY-MM-DD.jsonl`); writes one JSON line; flush + `os.fsync`.
Returns the written envelope (useful for tests and chained logging).

**`codepilot/observability/tracing.py`**
OTel adapter. `configure_tracing(service_name, otlp_endpoint, console_export)` builds a `TracerProvider` with `Resource{service.name}`. If `otlp_endpoint` set, attaches `BatchSpanProcessor(OTLPSpanExporter)` (lazy import — gRPC dep optional). If `console_export`, attaches `SimpleSpanProcessor(ConsoleSpanExporter)`. `start_span(name, **attrs)` context manager — pulls `context_snapshot()` and writes each as `codepilot.<key>` attribute on the span; user kwargs land as raw attrs. `reset_for_tests()` nukes the global provider so `set_tracer_provider` works again.

**`codepilot/observability/trace_cli.py`**
Forensics tool. `python -m codepilot.observability.trace_cli <trace_id> [--log-dir LOGS] [--json]`.
- `_iter_jsonl(path)` — robust reader, skips malformed lines.
- `collect(log_dir, trace_id)` — globs `*.jsonl` under `log_dir`, filters by `trace_id`, normalises `timestamp` → `ts`, sorts by ts, tags rows with `_source` filename.
- `render(rows)` — pretty single-line-per-event human view with `state`, `agent`, `event`, msg.
- `main(argv)` — argparse, returns 0 if rows found, 1 if not.

**`codepilot/__main__.py` (modified)**
`doctor` subcommand now constructs `Settings()`, dumps `.model_dump()` to stdout, masks every secret field to `***SET***`. Closes the Phase 0 `extra="ignore"` typo risk — operators can confirm config resolution.

### Tests (53 new)

**`tests/unit/test_context.py`** (9)
`TestBindTask` — trace_id minted vs explicit; tokens reset on exit. `TestBindSpan` — parent/child chain via nested spans; trace inherited. `TestBindState` — set + reset. `TestDecorator` — `@with_trace` wraps both sync and async callables. `TestAsyncPropagation` — `asyncio.create_task` inherits contextvars (the property that justifies using contextvars at all). `TestSnapshot` — empty when nothing bound.

**`tests/unit/test_redaction.py`** (19)
`TestSecretKeys` parametrized over 8 known keys + case insensitivity. `TestPatternScrubbing` parametrized over 6 token shapes embedded in strings. `TestStructure` — nested dicts, lists, primitive passthrough, immutability of input.

**`tests/unit/test_logger.py`** (5)
Fixture auto-resets module state. Asserts: (1) emitted JSON line carries trace/span/issue/repo from contextvars; (2) `github_token=...` value scrubbed at field level; (3) inline `ghp_...` in event message scrubbed at pattern level; (4) `configure()` is idempotent; (5) `DEBUG` filtered when level is `INFO`.

**`tests/unit/test_audit.py`** (9)
`TestEnvelope` — required fields present; missing trace_id raises. `TestSchemaValidation` — `pr.opened` missing `url` raises; `hitl.decision` invalid enum raises; unknown event passes envelope-only check. `TestApproverCapture` — same login lands on both `hitl.decision` and `pr.opened`. `TestRedactionInDetails` — secret in details scrubbed before write. `TestAppendOnlyOrdering` — N writes appear in insertion order. `TestRotation` — file path includes today's UTC date.

**`tests/unit/test_tracing.py`** (4)
Uses `InMemorySpanExporter` to verify span attrs after end (in-progress spans don't expose them reliably). Confirms: span yielded; codepilot context attrs written; user kwargs (`retry=1`, `agent="coder"`) preserved as raw types; `start_span` survives no-endpoint config.

**`tests/unit/test_trace_cli.py`** (7)
End-to-end. `_full_lifecycle(log_dir)` simulates pickup → classify → explore (2 events) → code → test → HITL request → HITL decision → branch → commit → PR open → done. Asserts: every required event reconstructs; rows sorted; approver login recoverable from collected rows; second concurrent task's events excluded by `trace_id` filter; CLI exit 0 for known trace, 1 for unknown, `--json` produces valid array of ≥ 12 entries.

---

## Architecture (one task end to end)

```
issue picked up
   │  bind_task(issue_id) ─→ trace_id minted, pinned in contextvars
   ▼
Orchestrator emits  audit.write(ISSUE_PICKED_UP, ...)
   │
   ├─→ structlog "issue.classified"   (state: TRIAGED)
   ├─→ bind_state("EXPLORING") + bind_span("explore", "explorer")
   │     structlog "repo_map.built", "files.retrieved"
   ├─→ bind_state("IMPLEMENTING") + bind_span("code", "coder")
   │     structlog "edit.applied" per file, "sandbox.execute" per cmd
   ├─→ bind_state("TESTING")  → structlog "tests.run"
   ├─→ HITL → audit.write(HITL_REQUESTED) → audit.write(HITL_DECISION{approver_login})
   ├─→ audit.write(BRANCH_CREATED) / COMMIT_CREATED / PR_OPENED{approver_login}
   └─→ audit.write(TASK_COMPLETE{outcome, duration_ms})
   ▼
trace_cli <trace_id> stitches both streams, sorted by ts
```

Two streams:
- **Main log** (`codepilot.jsonl`, rotated daily, 30-day retention) — every structlog event.
- **Audit log** (`audit-YYYY-MM-DD.jsonl`, append-only, fsync per write, midnight-only rotation) — only events that record irreversible/privileged actions: pickup, guardrail blocks, HITL requests + decisions, branches, commits, PRs, completion.

The trace CLI joins them by `trace_id`.

---

## FAQ

### Q1. Why two log streams instead of one?
The main log is verbose and noisy — every tool call, every retry, every span. The audit log is a permanent record of decisions that move money / risk: who approved a PR to main, what guardrail fired and why, which branch got created. Mixing them means rotation policy + retention + write semantics fight each other. Splitting means audit can be append-only with fsync (slow but correct) while the main log can be buffered (fast).

### Q2. Why `contextvars` instead of passing `trace_id` as a function argument?
Subagents are spawned across threadpools and async tasks. Threading a `trace_id` through every signature pollutes APIs and is forgotten exactly once — the time it matters. `contextvars` propagate automatically across `asyncio.create_task` and `concurrent.futures` (with `copy_context`). Test `test_async_propagation` verifies this works.

### Q3. Why `bind_task` (per-task) and `bind_span` (per-call) — two levels?
- `trace_id` lives for the lifetime of one issue → PR. Stable. Greppable.
- `span_id` changes per agent invocation, with `parent_span_id` linking the chain.
That is the OpenTelemetry model. Following it means OTel + our log fields agree, which in turn means the OTLP exporter and `trace_cli` produce consistent views.

### Q4. Why structlog instead of `logging` + `extra={...}`?
- Native key-value pairs.
- Context binding via `contextvars.merge_contextvars` is built-in.
- Custom processors (redaction, ctx injection) are first-class.
- JSON renderer ships with the library.
Standard `logging` works, but every log line we want costs `extra={...}` ceremony, and one missed `extra` is a silent gap.

### Q5. Why JSONSchema-validate the audit log?
Audit is the source of truth for "who approved what." If a writer ships a malformed `pr.opened` (e.g. forgets `approver_login`), discovery happens months later during an incident. Hard-failing on validation at write time turns a future ambiguous incident into a current obvious bug.

### Q6. Why `fsync` per write? Isn't that slow?
Audit volume is tiny (≤ a few dozen events per task). The cost is dominated by network + LLM calls, not disk. Crash safety wins: if the box dies mid-task, the audit log up to the last fsync survives. The main structured log doesn't fsync — its loss is recoverable.

### Q7. Why both structlog field redaction AND a regex pattern scrubber?
Defense in depth.
- Field redaction catches the obvious case: a developer passes `github_token=<secret>` to the logger.
- Pattern scrubber catches the sneaky case: a stack trace includes `Authorization: Bearer ghp_xxxx` inside a string.
One alone leaks; both together don't.

### Q8. Why mint `trace_id` at issue pickup, not at orchestrator boot?
A trace is one task. The orchestrator processes many tasks across one process. A boot-scoped trace would conflate them — `trace_cli <id>` would return everything, useless.

### Q9. Why not use LangGraph thread IDs as `trace_id`?
- LangGraph thread IDs apply only to LLM-driven turns. Polling, branch creation, audit writes happen outside any thread.
- Forces dependency direction backward — observability would import LangGraph internals.
- Our `trace_id` is just a UUID; it can be set from a LangGraph thread ID later if useful.

### Q10. Why does `audit.write` require an active `bind_task`?
An audit row without `trace_id` is unjoinable — it can't be matched to anything in the main log or to the originating issue. Failing loudly at write time is cheaper than discovering the gap during an incident review.

### Q11. Why is the approver login captured in TWO places (`hitl.decision` AND `pr.opened`)?
- `hitl.decision` records the moment of approval: who, when, with what reason.
- `pr.opened.approver_login` lets a reviewer reading just the PR audit row see the chain of custody without joining tables.
Denormalizing one field is cheap and answers "who approved this PR?" with one grep.

### Q12. Why expose `trace_cli` as a Python module instead of a shell one-liner?
Three reasons:
1. JSONL parsing is robust to half-written lines (tests `_iter_jsonl` skips bad lines).
2. Cross-platform — works the same on Windows.
3. `--json` flag emits a structured payload other tooling can pipe into.
A shell version would solve none of these.

### Q13. Why daily rotation at UTC midnight specifically for audit?
Tasks routinely run for tens of minutes. Rotating mid-task would split a single trace across two files, slowing reconstruction. UTC anchors the boundary regardless of operator timezone — relevant when multiple operators in different zones share a remote box.

### Q14. Why no PII redaction (emails, names) in the redactor?
Audit must contain `approver_login` (a GitHub username, sometimes a real name). Redacting it defeats the purpose. PII concerns belong in retention policy + access control on the log files, not in scrubbing. Add a separate scrubber later if regulatory scope changes.

### Q15. Why does the OTel layer no-op without an OTLP endpoint?
Local dev should not require Jaeger/Tempo. The structured log + audit log give 100% of what's needed for debugging. OTel is the icing for production traces — nice to have, not load-bearing. Keeping it optional means a fresh clone runs without infra setup.

### Q16. Why `reset_for_tests()` instead of relying on pytest fixtures alone?
Both structlog and OpenTelemetry use module-level singletons. Pytest fixtures can't reset module state without explicit hooks. `reset_for_tests` is that hook — cheap, explicit, only used in tests.

### Q17. Why event names like `issue.picked_up` (dot-namespaced) instead of `IssuePickedUp`?
- Easy to grep: `grep '"event":"issue\.'` finds the whole pickup family.
- Easy to filter in OTel/Datadog by prefix.
- Easy to add subtypes later (`issue.picked_up.retry`) without invalidating the schema.

### Q18. What stops a future contributor from logging a secret?
Three layers:
1. Redactor catches values stored under known field names + token patterns.
2. `pyproject.toml` could add `bandit` rule (deferred to Phase 13 hardening).
3. `Settings` uses `SecretStr`, so `repr(s)` already masks. Most accidental logs stringify the settings object.
The redactor is the safety net, not the only line.

---

## Decisions Log

| # | Decision | Alternatives | Rationale |
|---|---|---|---|
| 1 | structlog as the logger | stdlib + JsonFormatter; loguru | native ctx integration, processor chain, JSON-first |
| 2 | Two streams (main + audit) | one stream, filtered later | conflicting durability semantics |
| 3 | JSONSchema validation in audit writer | runtime types only | hard-fail on malformed permanent records |
| 4 | `contextvars` for correlation | thread locals, explicit args | works across async + threading without ceremony |
| 5 | UUID `trace_id`, not LangGraph thread | reuse thread id | layer separation; trace exists outside LLM turns |
| 6 | fsync per audit write | buffered | crash safety > throughput at audit volumes |
| 7 | OTel optional (no-op without endpoint) | required | keeps dev install zero-infra |
| 8 | Approver login on both HITL_DECISION and PR_OPENED | only on decision | one-grep PR provenance |
| 9 | Trace CLI parses both ts and timestamp keys | normalize at write | structlog/jsonschema each have a default — accept both |

## Risks / Things to revisit

- **Test environment leakage**: structlog and OTel reset is ad-hoc. If a future test forgets `reset_for_tests`, ordering gets flaky. Wire into a session-scoped autouse fixture in `conftest.py` once a flake appears.
- **Log volume at scale**: With multiple in-flight tasks and verbose subagents, the main log can hit GB/day. Add a sampler in Phase 13 if hosted runs grow.
- **Audit log integrity**: Currently relies on filesystem honesty. Phase 13 hardening: append a hash chain (each row includes hash of previous row) for tamper-evidence.
- **PII in details**: Issue titles/bodies may contain emails. Redactor leaves them alone today. Decide policy before the first external customer.
