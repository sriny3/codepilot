# Phase 11 — Steering Doc: TUI (DeepAgents Refactor)

**Status:** complete — rewritten as 4-panel dashboard with HITL gate (2026-05-08)
**Owner:** frontend / UX
**Depends on:** Phase 10 (Orchestrator — `HITLCoordinator` target, streams events), Phase 0 (Scaffold — `textual` dependency)
**Unblocks:** Phase 12 (E2E — full pipeline display), Phase 13 (Hardening — graceful shutdown, log overflow protection)

> **NOTE — Architecture change.** The original single-column `Vertical(DataTable, Log)` layout with 5-column table and `upsert_task(TaskRow)` has been replaced by a 4-panel `Grid(2×2)` with three widget types and a HITL approval panel. `TaskRow.to_table_row()` and the internal `_task_keys` set are gone. The `IssuesPanel` table is now 3 columns only.

---

## Goal

Provide a live terminal dashboard for operators to monitor and control the autonomous pipeline. The TUI:

1. **Shows** a live feed of polled GitHub issues in a 3-column DataTable (IssuesPanel).
2. **Shows** the current task's state, skill, retry count, and todo checklist (ActiveTaskPanel).
3. **Streams** all pipeline events into a scrollable `Log` panel.
4. **Blocks** on HITL interrupts: shows an approval prompt (ApprovalPanel) and resumes the orchestrator thread when the operator types `[a]` or `[r]`.
5. **Exposes** thread-safe helpers (`post_append_log`, `post_upsert_issue`, `post_update_active_task`) so the background orchestrator thread can update the UI safely.
6. **Wires** all pieces in `__main__.py`: app → HITLCoordinator → orchestrator background thread → IssuePoller.

---

## Deliverables

| Artifact | Path | Purpose |
|---|---|---|
| Widget library | `codepilot/tui/widgets.py` | `IssuesPanel`, `ActiveTaskPanel`, `ApprovalPanel` |
| HITL coordinator | `codepilot/tui/hitl.py` | `HITLCoordinator` — threading.Event bridge |
| App | `codepilot/tui/app.py` | `CodePilotApp` — 4-panel Grid, approval handler |
| Models | `codepilot/tui/models.py` | `TaskStatus`, `TaskRow` (extended with skill + todos) |
| App tests | `tests/unit/test_tui_app.py` | 9 async tests — startup, widgets, upsert_issue, log, quit |

---

## Exit Criteria

- `CodePilotApp` starts headlessly without error.
- `IssuesPanel` DataTable has exactly **3 columns**: `#`, `Title`, `State`.
- `upsert_issue(id, title, state)` adds a new row; calling again with same id updates in-place (no duplicate rows); `CellDoesNotExist` caught internally.
- `append_log(message)` writes a line to the `Log` widget.
- `q` key exits cleanly.
- `ApprovalPanel` is hidden by default (`display: none`); `show_operation()` makes it visible.
- Typing `a` + Enter in the approval input calls `hitl.resolve(approved=True)` and hides the panel.
- Typing `r` + Enter calls `hitl.resolve(approved=False)` and hides the panel.
- `HITLCoordinator.request_approval()` blocks the calling thread until `resolve()` is called.
- `pytest` green: 731 passed, 3 skipped.

---

## Files

### Source

#### `codepilot/tui/widgets.py`

Three Textual `Vertical` subclass widgets:

**`IssuesPanel`**:
- `compose()` — `Static("GitHub Issues")` label + `DataTable(id="issues-table")`.
- `on_mount()` — adds 3 columns: `#` (key `"num"`), `Title` (key `"title"`), `State` (key `"state"`).
- `upsert_issue(issue_id, title, state)` — tries `table.update_cell(key, col, val)` for all 3 cells; catches `CellDoesNotExist` (from `textual.widgets._data_table`) and falls back to `table.add_row(...)`. Titles truncated at 36 chars. State cell rendered as `f"{icon} {state.lower()}"` using `_STATE_ICON` dict (e.g., `"● triaged"`, `"◌ exploring"`, `"✓ done"`).

**`ActiveTaskPanel`**:
- `compose()` — `Static(id="task-title")` + `Static(id="task-agent")` + `Static(id="task-skill")` + `ListView(id="task-todos")`.
- `update_task(issue_id, title, state, skill, retry, todos)` — updates `#task-title` to `"Issue #{id}: {title}"`, `#task-agent` to `"Status: {state}  Agent: {agent} (retry {retry}/3)"` (agent derived from `_STATE_AGENT`), `#task-skill` to `"Skill: {skill}"`, and rebuilds `ListView` with `ListItem(Label("[ ] {todo}"))` per entry.

**`ApprovalPanel`**:
- `DEFAULT_CSS` — `display: none` by default; `ApprovalPanel.--visible { display: block }`.
- `compose()` — `Static("Awaiting Approval", id="approval-title")` + `Static("", id="approval-description")` + `Input(placeholder="approve / reject / inspect", id="approval-input")`.
- `show_operation(operation, details)` — adds `"--visible"` CSS class; updates title to `f"⚠ {operation}"`; formats `details` dict as multi-line string `"  key: value"` per entry.
- `hide()` — removes `"--visible"`; clears `Input.value`.

**New helpers in `widgets.py`**:
- `_STATE_ICON: dict[str, str]` — maps state name to display glyph: `TRIAGED=●`, `EXPLORING=◌`, `IMPLEMENTING=◉`, `TESTING=◎`, `PR_OPENED=◈`, `DONE=✓`, `FAILED=✗`.
- `_STATE_AGENT: dict[str, str]` — maps state to responsible agent name: `TRIAGED/DONE/FAILED=Orchestrator`, `EXPLORING=RepoExplorer`, `IMPLEMENTING=Coder`, `TESTING=TestAgent`, `PR_OPENED=PRAgent`.

#### `codepilot/tui/hitl.py`

**`HITLCoordinator`**:
- `__init__(app)` — stores `app` reference; creates `threading.Event()`; sets `_approved = False`.
- `request_approval(operation, details) → bool` — clears event, resets `_approved = False`, calls `app.call_from_thread(app.show_approval_panel, operation, details)` to show the panel on the Textual event loop, then blocks on `self._event.wait()`. Returns `_approved` when unblocked.
- `resolve(*, approved: bool)` — sets `_approved`, then calls `self._event.set()` to unblock the waiting orchestrator thread.

Two threads are involved: the orchestrator thread calls `request_approval()` and blocks; the Textual thread calls `resolve()` via the `on_input_submitted` handler. They communicate only through the `threading.Event` — no shared mutable state beyond `_approved` (set before `event.set()`, read after `event.wait()`, so no race).

#### `codepilot/tui/app.py`

**`NewTaskModal(ModalScreen[str | None])`** — fullscreen input modal:
- `compose()` — `Label("Enter a free-form coding task:")` + `Input(placeholder="...", id="new-task-input")`.
- `on_input_submitted(event)` — calls `self.dismiss(event.value.strip() or None)`.
- `on_key(event)` — calls `self.dismiss(None)` on `escape`.

**`CodePilotApp(App[None])`**:
- `TITLE = "CodePilot"`, `SUB_TITLE = "autonomous coding agent"`.
- `CSS` — `Grid { grid-size: 2 2; }` for 2×2 panel layout.
- `BINDINGS` — `q` (quit), `l` (toggle log), `i` (new task), `s` (skip issue).
- `__init__(*, max_log_lines=1000)` — stores `_max_log_lines`; sets `_hitl: HITLCoordinator | None = None`; sets `_on_ready: (() -> None) | None = None` (ready gate for background thread); creates `_task_queue: asyncio.Queue[str]` for manual task submissions.
- `on_mount()` — fires `_on_ready()` callback if set (signals background thread that Textual is running).
- `compose()` — `Header` + `Grid(IssuesPanel, ActiveTaskPanel, Log(max_lines=…, id="event-log"), ApprovalPanel)` + `Footer`.

Thread-safe panel update helpers (called from orchestrator thread via `call_from_thread`):
- `append_log(message)` / `post_append_log(message)` — sync/async variants.
- `upsert_issue(id, title, state)` / `post_upsert_issue(...)`.
- `update_active_task(id, title, state, skill, retry, todos)` / `post_update_active_task(...)` — note `title` is the second parameter (added vs original design).
- `show_approval_panel(operation, details)` / `hide_approval_panel()`.

**`on_input_submitted(event: Input.Submitted)`** — fires when user presses Enter in any `Input`. Guards on `event.input.id == "approval-input"`. Parses `value.strip().lower()`:
- `a / approve / y / yes` → `approved = True`
- `r / reject / n / no` → `approved = False`
- anything else → logs hint, returns without resolving

On valid input: `hide_approval_panel()`, then `self._hitl.resolve(approved=approved)` if `_hitl` is not `None`.

Keybinding actions: `action_toggle_log()` toggles `Log.display`; `action_new_task()` pushes `NewTaskModal` — on dismiss with a non-empty string, appends a log line and enqueues the task into `_task_queue`; `action_skip_issue()` logs a placeholder message.

#### `codepilot/tui/models.py`

**`TaskStatus(str, Enum)`** — `PENDING`, `TRIAGED`, `EXPLORING`, `IMPLEMENTING`, `TESTING`, `PR_OPENED`, `DONE`, `FAILED`. Present for backward compatibility; not used by `IssuesPanel` (which receives raw state strings).

**`TaskRow`** — dataclass with `issue_id`, `title`, `status`, `retry_count`, `pr_url`, `skill: str = ""`, `todos: list[str] = field(default_factory=list)`. Extended with `skill` and `todos` during refactor to support `ActiveTaskPanel.update_task()`.

#### `codepilot/__main__.py` (run command — wiring)

Key helpers and wiring for TUI:

**State inference** (module-level):
- `_STATE_ORDER` — list defining valid state progression order.
- `_TOOL_STATE: dict[str, str]` — maps tool call name → state it implies (e.g., `"classify_issue"→"TRIAGED"`, `"build_repo_map"→"EXPLORING"`).
- `_SUBAGENT_STATE: dict[str, str]` — maps subagent name → state (e.g., `"coder"→"IMPLEMENTING"`).
- `_advance(current, candidate) → str` — returns `candidate` only if it's later in `_STATE_ORDER` than `current`.
- `_infer_state(messages) → (state, skill, todos)` — walks LangGraph message list; advances state via `_TOOL_STATE` and `_SUBAGENT_STATE`; extracts `skill` from `classify_issue` result content; extracts `todos` from `write_todos` content lines.
- `_msg_log_line(msg) → str | None` — formats one LangGraph message into a human-readable log line: tool calls → `"[Orchestrator] → tool(args)"`, tool results → `"[tool_name] result_snippet"`, AI text → `"[Orchestrator] snippet"`.

**Startup and wiring**:
- `app = CodePilotApp(...)` created before `build_orchestrator` so `HITLCoordinator(app)` can be wired.
- `app._hitl = hitl` — set after both are constructed.
- `app_ready = threading.Event()` + `app._on_ready = app_ready.set` — ready gate; background thread calls `app_ready.wait()` before touching any TUI methods.

**`_run_orchestrator(issue_id, title, body) → None`** — async coroutine:
- Posts initial `TRIAGED` state to TUI immediately.
- Streams orchestrator events in `stream_mode="values"`.
- Per event: logs new messages via `_msg_log_line()`; calls `_infer_state()` on full message list; updates `IssuesPanel` and `ActiveTaskPanel` on state change; increments `retry` counter when state stays `TESTING`.

**`_pipeline_loop()`** — async main loop:
- Waits for `app_ready` before touching the TUI.
- Drains `app._task_queue` for manual tasks submitted via `[i]`.
- Streams `IssuePoller` or runs in polling-disabled mode with manual task support.

- `app.run()` blocks the main thread; orchestrator runs in a daemon background thread.
- `stop_bg.set()` called after `app.run()` returns (user quit) to terminate the background loop.

### Tests

#### `tests/unit/test_tui_app.py` (9 async tests)

Uses `app.run_test()` async context manager (Textual's headless driver):

- `test_app_starts_without_error` — `app.is_running` is True after `pilot.pause()`.
- `test_data_table_present` — `app.query_one(DataTable)` is not None.
- `test_log_widget_present` — `app.query_one(Log)` is not None.
- `test_table_has_three_columns` — `len(table.columns) == 3`.
- `test_upsert_issue_adds_row` — after `app.upsert_issue(42, "fix login", "EXPLORING")`, `table.row_count == 1`.
- `test_upsert_issue_updates_existing_row` — upsert same id twice → `row_count == 1`.
- `test_upsert_multiple_issues` — 3 different ids → `row_count == 3`.
- `test_append_log_writes_line` — `log.line_count >= 1` after `append_log`.
- `test_quit_binding_exits` — pressing `q` exits without exception.

---

## Architecture

```
codepilot run
    │
    ├─ app = CodePilotApp(max_log_lines=…)
    ├─ hitl = HITLCoordinator(app)   →   app._hitl = hitl
    ├─ app_ready = threading.Event()
    ├─ app._on_ready = app_ready.set  ← fired by on_mount()
    │
    ├─ [background daemon thread]
    │     app_ready.wait()            ← blocks until Textual started
    │     asyncio loop
    │       _drain_manual()           ← drains app._task_queue (from [i])
    │       IssuePoller.stream(interval_sec=…)   (or manual-only mode)
    │         for each issue:
    │           _run_orchestrator(id, title, body)
    │             app.post_upsert_issue(id, title, "TRIAGED")
    │             app.post_update_active_task(id, title, "TRIAGED", …)
    │             orchestrator.stream({messages}, config, stream_mode="values")
    │               per event:
    │                 _msg_log_line(msg) → app.post_append_log(line)
    │                 _infer_state(messages) → state/skill/todos
    │                 state change → app.post_upsert_issue + post_update_active_task
    │
    └─ app.run()   [main thread — Textual event loop]
            │
            ├─ Grid (2×2)
            │    ├─ IssuesPanel   [top-left]
            │    ├─ ActiveTaskPanel [top-right]
            │    ├─ Log           [bottom-left]
            │    └─ ApprovalPanel [bottom-right, hidden by default]
            │
            ├─ [orchestrator hits interrupt_on="open_pr"]
            │    HITLCoordinator.request_approval(op, details)
            │      → app.call_from_thread(app.show_approval_panel, …)
            │      → blocks on threading.Event.wait()
            │
            ├─ [user types "a" + Enter in approval input]
            │    on_input_submitted → hitl.resolve(approved=True)
            │      → threading.Event.set()
            │      → orchestrator unblocks, resumes graph
            │
            └─ [user presses q]
                 app exits → stop_bg.set()
```

---

## FAQ

**Q: Why is `IssuesPanel` 3 columns, not 5 like the original?**
The original 5-column design (Issue, Title, State, Retry, PR) was designed for `TaskRow` objects from the class-based Orchestrator. The DeepAgents refactor made those fields implicit in the graph state — retry count and PR URL are not surfaced per-issue in the new flow. `ActiveTaskPanel` shows retry and skill for the currently active task. The split keeps each panel focused.

**Q: Why `upsert_issue(id, title, state)` instead of `upsert_task(TaskRow)`?**
The orchestrator background thread knows issue ID, title, and current state at the moment it calls the update. It doesn't hold a `TaskRow` object — the row model was coupled to the old `WorkingMemory` class. Plain scalars are simpler to call from thread context and don't require importing the TUI models on the orchestrator side.

**Q: Why catch `CellDoesNotExist` from a private module path?**
`DataTable` raises `CellDoesNotExist` when `update_cell` is called with a key that doesn't exist. The exception isn't re-exported from a stable public path in Textual. Catching `Exception` broadly would swallow bugs; `CellDoesNotExist` is specific. The private import path is a known Textual pattern accepted by the community.

**Q: Why `threading.Event` in `HITLCoordinator` rather than an asyncio Event?**
The orchestrator background thread runs in a separate asyncio loop. The TUI runs in its own event loop (Textual's). Sharing an asyncio Event across loops is error-prone. `threading.Event` is loop-agnostic — it works across any thread boundary. `call_from_thread` bridges from the orchestrator thread to the Textual loop for the UI update.

**Q: Why `_hitl: HITLCoordinator | None = None` instead of requiring it in `__init__`?**
`CodePilotApp` is also used in tests that don't need HITL. Making it optional keeps the test setup simple — tests create `CodePilotApp()` with no arguments. Production wires it afterward via `app._hitl = hitl` before `app.run()`.

**Q: What happens if the user dismisses the approval panel with `q` (quit)?**
The orchestrator thread is still blocked on `threading.Event.wait()`. The daemon thread is killed when the process exits. This is intentional — there's no clean "cancel approval" path yet. Phase 13 should intercept the quit keybinding and call `hitl.resolve(approved=False)` before exiting.

---

## Decisions Log

| # | Decision | Alternatives considered | Rationale |
|---|---|---|---|
| 1 | 4-panel Grid (2×2) | Single `Vertical(DataTable, Log)` | Dedicated panels for issues list, active task detail, log, and HITL are more readable |
| 2 | `upsert_issue(id, title, state)` plain params | `upsert_task(TaskRow)` | No dependency on TaskRow from orchestrator thread; simpler cross-module coupling |
| 3 | 3-column DataTable | 5-column (Issue/Title/State/Retry/PR) | Retry and PR are per-active-task details now shown in ActiveTaskPanel |
| 4 | `CellDoesNotExist` from private path | Broad `except Exception` | Specific exception; broad catch hides real bugs |
| 5 | `threading.Event` for HITL | asyncio Event | Works across event loop boundaries without coordination |
| 6 | `_hitl = None` (optional wiring) | Require HITLCoordinator in __init__ | Test-friendly; tests don't need HITL wired |
| 7 | `on_input_submitted` in `CodePilotApp` | Handler in `ApprovalPanel` | App-level handler has access to `_hitl`; panel is a pure display widget |

---

## Risks / Things to Revisit

- **Quit with pending HITL**: `q` kills the process while the orchestrator thread is blocked. Add a guard in `action_quit()` that calls `hitl.resolve(approved=False)` if `_hitl` is set and event is not set.
- **Log overflow on long sessions**: `Log(max_lines=cfg.tui_max_log_lines)` is configured but the default is 1000 — sufficient for most tasks. Consider flushing to disk when the limit is hit.
- **No error detail in IssuesPanel**: Failed tasks show `FAILED` in the State column with no reason. Add a hover tooltip or click-to-expand in Phase 13.
- **`s` key binding stub**: `action_skip_issue()` logs a placeholder message. Wire to IssuePoller or orchestrator skip queue in Phase 13.
- **ApprovalPanel inspect mode**: Placeholder text says `inspect` but there's no inspect handler. Add a handler that reads the current sandbox diff and displays it before committing.
- **Manual task IDs**: Free-form tasks submitted via `[i]` use a decrementing negative integer as `issue_id` (0, -1, -2...). Phase 12 should display these with a `[manual]` label rather than `#-1`.
