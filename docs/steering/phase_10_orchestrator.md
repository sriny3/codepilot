# Phase 10 — Steering Doc: Orchestrator

**Status:** complete
**Owner:** orchestration
**Depends on:** Phase 6 (RepoExplorer), Phase 7 (Coder), Phase 8 (TestAgent), Phase 9 (PRAgent), Phase 2 (Memory — `WorkingMemory`, `TaskState`), Phase 0 (Settings — `max_retries`)
**Unblocks:** Phase 11 (TUI — drives `Orchestrator.run_issue` from UI), Phase 12 (E2E — full pipeline test)

---

## Goal

Coordinate all agents in the correct order for a single issue and implement the retry loop. The Orchestrator:

1. **Drives** the state machine: TRIAGED → EXPLORING → IMPLEMENTING → TESTING → PR_OPENED → DONE.
2. **Retries** the Coder when tests fail, up to `max_retries` times, passing failure details as a `skill_prompt`.
3. **Fails** the task cleanly (`wm.fail(...)`) when retries are exhausted or any agent raises.
4. **Emits** `Event.TASK_COMPLETE` on success.

All agents are constructor-injected — any object with the matching `run()` signature satisfies the contract. This keeps the Orchestrator fully testable with lightweight fakes.

## Deliverables

| Artifact | Path | Purpose |
|---|---|---|
| Orchestrator | `codepilot/orchestrator/orchestrator.py` | `Orchestrator`, `_format_failure_hint` |
| Public API | `codepilot/orchestrator/__init__.py` | Re-exports `Orchestrator` |
| Tests | `tests/unit/test_orchestrator.py` | 21 tests — hint formatting, pipeline, retry, failure paths |

## Exit Criteria

- Happy path: `wm.state == DONE` after `run_issue` with passing tests.
- Retry: Coder called twice when first test run fails; `wm.retry_count == 1`.
- Exhausted: `wm.state == FAILED` after `max_retries` failures; PR agent never called.
- Agent exception: caught, `wm.fail(str(exc))` called, FAILED returned.
- `_format_failure_hint`: includes test names for failures list; caps at 5; handles `None`.
- PR labels and reviewers forwarded to PR agent.
- Custom `RunConfig` forwarded to test agent.
- `pytest` green: 769 passed, 2 skipped.

## Files

### Source

#### `codepilot/orchestrator/orchestrator.py`

**`_format_failure_hint(test_results: TestRunSummary | None) → str`** — converts failed test results into a `skill_prompt` for the Coder. `None` → generic message. No failures list → `"Tests failed (N failure(s)). Fix the failing tests."`. Up to 5 failures listed as `FAILED <test>: <reason>`.

**`Orchestrator`**:
- `__init__(repo_explorer, coder, test_agent, pr_agent, *, max_retries=3, run_config=None)` — all agents injected. `run_config=None` → `RunConfig(command="pytest")`.
- `run_issue(wm, issue_ref, *, source_root, pr_labels=(), reviewers=()) → WorkingMemory`:
  1. `repo_explorer.run(wm, source_root, issue_ref.body)` → TRIAGED → EXPLORING.
  2. `coder.run(wm, source_root, issue_ref.body)` → EXPLORING → IMPLEMENTING.
  3. Loop `range(max_retries + 1)`:
     - `test_agent.run(wm, run_config)` → IMPLEMENTING → TESTING.
     - If `wm.test_results.failed == 0`: break.
     - If `attempt < max_retries`: `wm.bump_retry()`, `_format_failure_hint()`, `coder.run(..., skill_prompt=hint)` → TESTING → IMPLEMENTING.
     - Else: `wm.fail("max retries exceeded")`, return early.
  4. `pr_agent.run(wm, issue_ref.title, pr_labels=..., reviewers=...)` → TESTING → PR_OPENED.
  5. `wm.transition(DONE)`.
  6. Emit `Event.TASK_COMPLETE`.
  7. Any exception caught: `wm.fail(str(exc))` if not already terminal.

#### `codepilot/orchestrator/__init__.py`

Re-exports: `Orchestrator`.

### Tests

#### `tests/unit/test_orchestrator.py` (21 tests)

Two classes:

**`TestFormatFailureHint`** (4):
- `None` input → message contains "failed".
- No failures list → count in message.
- Failures list → test name and reason included.
- Capped at 5 entries regardless of failures length.

**`TestOrchestrator`** (17):
- Happy path → DONE.
- Returns same `wm` object.
- Explorer called once.
- Coder receives `issue_ref.body`.
- Test agent called at least once.
- PR agent called when tests pass.
- PR agent not called when tests always fail.
- Coder called twice on one retry (initial + retry).
- `wm.retry_count == 1` after one retry.
- `wm.state == FAILED` after max retries exhausted.
- No extra retry when tests pass on first attempt.
- Failure hint with test name in `skill_prompt` on retry.
- Issue title forwarded to PR agent.
- `pr_labels` forwarded to PR agent.
- Custom `RunConfig.command` reaches test agent.
- Default `RunConfig` contains "pytest".
- Agent exception → `wm.state == FAILED`.

## Architecture

```
Orchestrator.run_issue(wm, issue_ref, source_root=…)
    │
    ├─► repo_explorer.run(wm, source_root, issue_ref.body)
    │       TRIAGED → EXPLORING
    │       wm.relevant_files populated
    │
    ├─► coder.run(wm, source_root, issue_ref.body)
    │       EXPLORING → IMPLEMENTING
    │       wm.proposed_diff populated
    │
    ├─► for attempt in range(max_retries + 1):
    │       │
    │       ├─► test_agent.run(wm, run_config)
    │       │       IMPLEMENTING → TESTING
    │       │       wm.test_results populated
    │       │
    │       ├─── if failed == 0: break ──────────────────────────────────┐
    │       │                                                             │
    │       ├─── if attempt < max_retries:                               │
    │       │       wm.bump_retry()                                      │
    │       │       hint = _format_failure_hint(wm.test_results)         │
    │       │       coder.run(wm, …, skill_prompt=hint)                  │
    │       │           TESTING → IMPLEMENTING                           │
    │       │                                                             │
    │       └─── else: wm.fail("max retries exceeded") → FAILED, return  │
    │                                                                     │
    ├─► pr_agent.run(wm, issue_ref.title, …) ◄──────────────────────────┘
    │       TESTING → PR_OPENED
    │
    ├─► wm.transition(DONE)
    │
    └─► log Event.TASK_COMPLETE
```

## FAQ

**Q: Why is `run_issue` on the Orchestrator rather than a free function?**
Configuration (`max_retries`, `run_config`) is stable per-session but varies per deployment. Constructor injection keeps those values out of the method signature. The Orchestrator can be constructed once and called many times (one per issue in the poller loop).

**Q: Why does the Orchestrator accept `Any` typed agents rather than typed Protocols?**
The four agents have different constructor signatures and aren't interchangeable. Defining a separate `@runtime_checkable` Protocol for each just to satisfy `isinstance` checks in `__init__` would add ~40 lines with no runtime benefit — the duck-typed `run()` call already errors clearly if the contract is violated. `Any` keeps it honest: the Orchestrator is a structural coordinator, not a type gatekeeper.

**Q: Why is `_format_failure_hint` a module-level function, not a method?**
It's a pure transformer (`TestRunSummary | None → str`) with no access to `self`. Keeping it separate makes it independently testable and avoids coupling the formatting logic to the Orchestrator's retry mechanics.

**Q: Why cap `_format_failure_hint` at 5 failures?**
LLM context windows aren't unlimited. 5 failure samples give the Coder enough signal to identify the pattern without bloating the prompt. The full failure list is already in `wm.test_results.failures` for tools that need it.

**Q: Why does the retry loop use `range(max_retries + 1)` rather than a while loop?**
`range(max_retries + 1)` makes the maximum iteration count obvious at a glance and avoids a separate counter variable. The loop body runs `max_retries + 1` times: one initial attempt plus up to `max_retries` re-code+re-test cycles.

**Q: Why catch all exceptions rather than specific ones?**
Any agent can fail for unpredictable reasons (LLM timeout, network error, file permission, etc.). Catching all exceptions ensures the `WorkingMemory` always ends in a terminal state and the poller loop continues with the next issue. Specific exception types would leave gaps. The error is logged with full detail for post-mortem.

## Decisions Log

| # | Decision | Alternatives considered | Rationale |
|---|---|---|---|
| 1 | Inject all four agents | Instantiate inside `run_issue` | Testability; agents have different setup requirements per deployment |
| 2 | `Any` types for agents | Per-agent Protocol definitions | No runtime `isinstance` checks needed; duck typing is sufficient |
| 3 | `range(max_retries + 1)` loop | `while` loop with counter | Explicit iteration count; no off-by-one risk |
| 4 | `_format_failure_hint` as module function | Method on Orchestrator | Pure function; independently testable; no `self` needed |
| 5 | Catch all exceptions | Catch specific exceptions | Guarantees terminal state regardless of failure mode |
| 6 | `run_config=None` defaults to `pytest` | Require explicit RunConfig | Safe default for most Python projects; overridable from settings |

## Risks / Things to Revisit

- **Duration tracking**: `duration_ms=0` is hardcoded in `Event.TASK_COMPLETE`. Add wall-clock timing (`time.monotonic()`) at task start.
- **Concurrency**: `run_issue` is synchronous. Phase 11/12 may need async or thread-pool support for `max_inflight_tasks > 1`. Wrapping in `asyncio.to_thread` is the minimal path.
- **Source root per-task**: `source_root` is passed at `run_issue` time. If two tasks share the same source root but different sandboxes, the Orchestrator works correctly. If they share a sandbox, writes from one task may pollute another — the sandbox should be task-scoped, not shared.
- **Settings integration**: `max_retries` and `RunConfig` should be driven by `Settings.max_retries` and a `Settings.test_command` field. Phase 12 should wire `get_settings()` into the Orchestrator factory.
- **Retry with no diff**: If the Coder fails to produce a diff on retry (e.g., LLM returns no edits), the same broken code is re-tested. Add a guard: skip the test run if `wm.proposed_diff` hasn't changed since the last attempt.
