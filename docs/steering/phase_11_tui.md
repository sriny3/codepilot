# Phase 11 — Steering Doc: TUI

**Status:** complete
**Owner:** frontend / UX
**Depends on:** Phase 0 (Scaffold — `textual` dependency in `pyproject.toml`), Phase 10 (Orchestrator — `TaskState` values), Phase 2 (Memory — `TaskState` enum)
**Unblocks:** Phase 12 (E2E — full pipeline display), Phase 13 (Hardening — graceful shutdown via `q` binding)

---

## Goal

Provide a live terminal dashboard so operators can monitor in-flight tasks. The TUI:

1. **Displays** a `DataTable` with one row per issue: issue number, title, state, retry count, PR URL.
2. **Streams** event log lines into a scrollable `Log` panel.
3. **Accepts** `q` to quit cleanly.
4. **Exposes** `upsert_task(row)` and `append_log(message)` as the integration surface for the Orchestrator — both safe to call from a worker thread via `App.call_from_thread()`.
5. **Wires** the `codepilot run` CLI command to launch the app.

## Deliverables

| Artifact | Path | Purpose |
|---|---|---|
| Models | `codepilot/tui/models.py` | `TaskStatus`, `TaskRow`, `TaskRow.from_working_memory` |
| App | `codepilot/tui/app.py` | `CodePilotApp` (Textual `App`) |
| Public API | `codepilot/tui/__init__.py` | Re-exports `CodePilotApp`, `TaskRow`, `TaskStatus` |
| CLI wiring | `codepilot/__main__.py` | `run` subcommand calls `CodePilotApp().run()` |
| Model tests | `tests/unit/test_tui_models.py` | 21 tests — enum, row fields, table cells, from_working_memory |
| App tests | `tests/unit/test_tui_app.py` | 9 async tests — startup, widgets, upsert, log, quit |

## Exit Criteria

- `CodePilotApp` starts headlessly without error.
- `DataTable` has 5 columns: Issue, Title, State, Retry, PR.
- `upsert_task` adds a new row; calling again with same issue ID updates, not duplicates.
- `append_log` writes a line to the `Log` widget.
- `q` key exits cleanly.
- `TaskStatus` contains all `TaskState` values plus `PENDING`.
- `TaskRow.to_table_row()` returns 5-element `tuple[str, ...]`; long titles truncated with `…`.
- `TaskRow.from_working_memory` maps unknown state to `PENDING`.
- `codepilot run` exits without import error (CLI wiring intact).
- `pytest` green: 798 passed, 2 skipped.

## Files

### Source

#### `codepilot/tui/models.py`

**`TaskStatus(str, Enum)`** — mirrors all `TaskState` values plus `PENDING` (for issues not yet handed to the Orchestrator). Pure Python, no Textual import.

**`TaskRow`** — dataclass: `issue_id: int`, `title: str`, `status: TaskStatus = PENDING`, `retry_count: int = 0`, `pr_url: str = ""`.
- `to_table_row() → tuple[str, str, str, str, str]` — returns 5 display strings. Titles longer than 38 chars are truncated and appended `…`.
- `from_working_memory(issue_id, title, *, state, retry_count=0, pr_url="")` — factory that maps a `TaskState` value string to `TaskStatus`; unknown values fall back to `PENDING`.

#### `codepilot/tui/app.py`

**`CodePilotApp(App[None])`**:
- `compose()` → `Header`, `Vertical(DataTable, Log)`, `Footer`.
- `on_mount()` → `add_column(label, key=...)` for 5 columns (keys: `"issue"`, `"title"`, `"state"`, `"retry"`, `"pr"`).
- `upsert_task(row: TaskRow)` — checks internal `_task_keys: set[str]`; adds row if new (`add_row(*cells, key=str(issue_id))`), updates cells via `update_cell(row_key, col_key, value)` if existing.
- `append_log(message: str)` — delegates to `Log.write_line(message)`.
- `BINDINGS = [("q", "quit", "Quit")]`.

#### `codepilot/__main__.py`

Added `run` branch: imports `CodePilotApp` and calls `.run()`. Returns 0.

#### `codepilot/tui/__init__.py`

Re-exports: `CodePilotApp`, `TaskRow`, `TaskStatus`.

### Tests

#### `tests/unit/test_tui_models.py` (21 tests)

Three classes:

- `TestTaskStatus` (4) — all `TaskState` values present in `TaskStatus`; is `str` subclass; `PENDING` exists; `FAILED` exists.
- `TestTaskRow` (12) — default status/retry/pr_url; `to_table_row` length; issue ID formatting; status in row; retry count; PR URL; long title truncated with `…`; short title unchanged; all cells are strings.
- `TestTaskRowFromWorkingMemory` (5) — known state mapped; unknown → PENDING; retry count forwarded; pr_url forwarded; issue_id and title set.

#### `tests/unit/test_tui_app.py` (9 async tests)

Uses `app.run_test()` async context manager (Textual's headless driver):
- App starts; `DataTable` present; `Log` present; 5 columns; `upsert_task` adds row; upsert same id doesn't duplicate; 3 tasks → 3 rows; `append_log` increments `log.line_count`; `q` exits.

## Architecture

```
codepilot run
    └─► CodePilotApp().run()
            │
            ├── Header (title + subtitle)
            ├── Vertical
            │     ├── DataTable  (5 cols: Issue/Title/State/Retry/PR)
            │     └── Log        (scrollable event stream)
            └── Footer (key hints)

Orchestrator thread → app.call_from_thread(app.upsert_task, row)
                    → app.call_from_thread(app.append_log, msg)
```

## FAQ

**Q: Why `upsert_task` / `append_log` as plain methods rather than Textual messages?**
Plain methods are trivially testable without posting/dispatching messages. The caller (Orchestrator worker thread) wraps them in `call_from_thread()`, which posts onto the Textual event loop. Internally they're synchronous Textual mutations — safe once on the event loop.

**Q: Why maintain `_task_keys: set[str]` internally rather than querying the DataTable?**
`DataTable` has no public `has_row(key)` method. Querying `get_row(key)` raises `RowDoesNotExist` on miss — using exceptions for control flow is slow and noisy. The internal set is O(1) and never desynchronises because `upsert_task` is the only writer.

**Q: Why not use Textual's `reactive` attributes for `TaskRow` state?**
Reactive attributes are for widget-level properties, not external data records. The task table is keyed by issue ID, not by a fixed widget tree position. `DataTable.update_cell` is the correct Textual primitive for this pattern.

**Q: Why `PENDING` in `TaskStatus` when `TaskState` doesn't have it?**
`TaskState.TRIAGED` is the first real state after an issue is picked up. Before the Orchestrator starts working (queue entry pre-dispatch), the TUI should show something meaningful. `PENDING` fills that gap without exposing Orchestrator internals to the display layer.

**Q: Why `to_table_row` returns `tuple[str, str, str, str, str]` rather than `list[str]`?**
A fixed-length tuple documents the column count in the type signature. The DataTable has exactly 5 columns; a list would allow variable-length returns that silently misalign columns at runtime.

**Q: Why this step now (after Orchestrator, before E2E)?**
All agent logic is complete and tested in isolation. Phase 11 adds the operator-facing layer — the display surface that E2E and hardening phases can drive. Doing it after Phase 10 means the `TaskState` enum is stable and won't change under the TUI models. Doing it before E2E means Phase 12 can test the full round-trip with a real screen.

**Q: What changes after this phase?**
`codepilot run` launches a working TUI. Phase 12 (E2E) can import `CodePilotApp`, inject fake tasks, and verify the table populates end-to-end. Phase 13 (Hardening) adds max log lines, error details, and the `call_from_thread` wrappers for safe multi-thread use.

**Q: What could break?**
- Textual version upgrades may change `DataTable.update_cell` or `Log.write_line` signatures — pin `textual` to a minor range in production.
- Calling `upsert_task` or `append_log` directly from a non-Textual thread (without `call_from_thread`) will cause silent data corruption or a crash inside Textual's event loop.
- The `q` binding quits immediately with no confirmation — any in-flight Orchestrator tasks are abandoned. Phase 13 should intercept the quit and drain the task queue first.

## Decisions Log

| # | Decision | Alternatives considered | Rationale |
|---|---|---|---|
| 1 | `upsert_task` + `append_log` as public methods | Textual custom messages | Simpler to test; `call_from_thread` handles thread safety |
| 2 | `_task_keys: set[str]` for existence check | `DataTable.get_row()` with exception | O(1), no exception overhead, more readable |
| 3 | String column keys (`"issue"`, `"title"`, …) | Storing `ColumnKey` objects | Strings work in `update_cell`; avoids storing extra state |
| 4 | `PENDING` status in `TaskStatus` | Map TRIAGED to TRIAGED | Distinguishes pre-dispatch from TRIAGED (Orchestrator started) |
| 5 | Async `run_test()` tests via pytest-asyncio | Sync unit tests with mocks | Tests actual Textual widget interactions; catches layout bugs |

## Risks / Things to Revisit

- **Thread safety**: `upsert_task` and `append_log` must be called via `App.call_from_thread()` from worker threads. Calling them directly from a non-Textual thread will corrupt Textual's internal state. Add a `post_upsert_task` wrapper in Phase 12 that automatically uses `call_from_thread`.
- **Log overflow**: `Log` widget has no `max_lines` enforced here. Long sessions will accumulate unbounded log entries. Set `max_lines` on the `Log` widget in Phase 13.
- **Error display**: Task failures show `FAILED` in the State column but don't surface the reason. Add a detail panel or tooltip in Phase 13.
- **No resize handling**: `DataTable` title column is fixed-width. Terminal resizes don't reflow. Textual handles this automatically but title truncation at 38 chars may look wrong on narrow terminals.
