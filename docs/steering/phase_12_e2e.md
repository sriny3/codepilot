# Phase 12 — Steering Doc: E2E

**Status:** complete
**Owner:** qa / integration
**Depends on:** All prior phases (Phases 0–11 — full stack must exist before wiring)
**Unblocks:** Phase 13 (Hardening — identifies real integration gaps to address)

---

## Goal

Wire all real agents together in a single test run, without LLM or GitHub API calls, to prove the full pipeline works end-to-end. Phase 12:

1. **Pipeline tests** (`tests/e2e/test_pipeline.py`) — `Orchestrator` drives real `RepoExplorerAgent`, `CoderAgent`, `TestAgent`, and `PRAgent` against a real `LocalSandbox` and a real source repo in `tmp_path`. `FakeEditProvider` replaces the LLM; `FakeTestRunner` replaces subprocess pytest; `FakeGitHub`/`FakeRepo` replaces the GitHub API. Covers happy path (DONE), one-retry recovery (DONE with `retry_count=1`), and exhausted-retry failure (FAILED, no PR).
2. **TUI pipeline tests** (`tests/e2e/test_tui_pipeline.py`) — `CodePilotApp` is driven via Textual's headless `run_test()` pilot. Verifies that `upsert_task` and `append_log` correctly reflect pipeline lifecycle events in the DataTable and Log widgets.

## Deliverables

| Artifact | Path | Purpose |
|---|---|---|
| Pipeline E2E | `tests/e2e/test_pipeline.py` | 14 tests — happy path, retry, failure, data flow assertions |
| TUI integration | `tests/e2e/test_tui_pipeline.py` | 8 async tests — task table + log driven by simulated pipeline events |

## Exit Criteria

- `TestHappyPath` (11 tests): `wm.state == DONE`; relevant files, repo map, diff, test results, PR note all populated; sandbox contains edited file; branch + commit + PR created in FakeRepo; issue body forwarded to edit provider; `retry_count == 0`.
- `TestRetryLoop` (3 tests): one-fail then pass → DONE with `retry_count == 1`; always-fail with `max_retries=2` → FAILED; no PR opened when retries exhausted.
- TUI (8 tests): initial table empty; new issue adds row; 5 status transitions on same issue ID = 1 row; 3 issues = 3 rows; 4 log lines written; FAILED status tracked; PR URL stored; retry count updates in place.
- `pytest` green: 820 passed, 2 skipped.

## Files

### Source

No new source files. Phase 12 is tests-only — it proves existing code integrates correctly.

### Tests

#### `tests/e2e/test_pipeline.py` (14 tests)

Two classes:

**`TestHappyPath`** (11) — uses a shared `done_wm` fixture that constructs the full `Orchestrator` with real agents and fake edges, then calls `run_issue`. Each test asserts a different aspect of the final state:
- `wm.state == DONE`
- `wm.relevant_files` non-empty (RepoExplorer found files)
- `sandbox.exists("repo_map.txt")` (RepoExplorer wrote map)
- `wm.proposed_diff` non-None and non-empty (Coder diffed)
- `wm.test_results.passed == 1, failed == 0` (TestAgent parsed runner output)
- `"PR #" in wm.notes` (PRAgent recorded note)
- `gh_repo.created_refs` non-empty (branch created)
- `"src/calculator.py"` in committed file paths (file committed to FakeRepo)
- `sandbox.read_file("src/calculator.py")` contains `"return a + b"` (edit applied)
- `edit_provider.last_issue_body == _ISSUE.body` (issue body flowed to LLM layer)
- `wm.retry_count == 0` (no retries on clean run)

**`TestRetryLoop`** (3) — constructs fresh orchestrators with configurable runners:
- `_TwoPhaseRunner` (fail on call 1, pass on call 2) → DONE, `retry_count == 1`.
- `FakeTestRunner(exit_code=1)` with `max_retries=2` → FAILED.
- Same failing runner, `max_retries=1` → `gh_repo.created_prs == []`.

**Source repo fixture** — creates `tmp_path/repo/src/calculator.py` (broken: `a - b`) and `tmp_path/repo/tests/test_calc.py` (tests `add(1, 2) == 3`). `FakeEditProvider` returns the fixed content `a + b`. Since `FakeTestRunner` is used, no subprocess pytest is needed — the fix is verified by reading sandbox state directly.

#### `tests/e2e/test_tui_pipeline.py` (8 async tests)

All use `app.run_test()` (headless Textual driver). Simulates the task lifecycle by calling `upsert_task` and `append_log` directly (as the Orchestrator would via `call_from_thread`):
- `test_initial_table_is_empty` — no tasks at startup.
- `test_new_issue_appears_in_table` — `upsert_task` adds row.
- `test_status_updates_do_not_add_duplicate_rows` — 5 upserts for same issue_id → 1 row.
- `test_multiple_issues_tracked_simultaneously` — 3 different issue IDs → 3 rows.
- `test_log_receives_pipeline_events` — 4 `append_log` calls → `log.line_count >= 4`.
- `test_failed_task_tracked` — FAILED status row appears.
- `test_pr_url_visible_after_completion` — DONE row with `pr_url` present.
- `test_retry_count_updates_in_table` — upsert with `retry_count=0` then `retry_count=2` → still 1 row.

## Architecture

```
tests/e2e/test_pipeline.py
    │
    └─► Orchestrator.run_issue(wm, _ISSUE, source_root=…)
            │
            ├─► RepoExplorerAgent(sandbox)          ← real AST parse, real file score
            │       writes repo_map.txt to sandbox
            │       sets wm.relevant_files
            │
            ├─► CoderAgent(sandbox, FakeEditProvider)  ← real sandbox I/O, fake LLM
            │       copies relevant_files to sandbox
            │       applies FileEdit(src/calculator.py, fixed_content)
            │       generates wm.proposed_diff via generate_sandbox_diff
            │
            ├─► TestAgent(sandbox, source_root, runner=FakeTestRunner)
            │       → FakeTestRunner returns "1 passed"
            │       sets wm.test_results
            │
            └─► PRAgent(gh_client=GitHubClient(FakeGitHub), sandbox)
                    create_branch → FakeRepo.created_refs
                    commit_files  → FakeRepo.updated_files / created_files
                    open_pr       → FakeRepo.created_prs
                    wm.notes.append("PR #1: …")

tests/e2e/test_tui_pipeline.py
    │
    └─► CodePilotApp.run_test() [headless]
            upsert_task(TaskRow(…)) → DataTable.add_row / update_cell
            append_log(msg)         → Log.write_line
```

## FAQ

**Q: Why this step now (after TUI, before Hardening)?**
All components exist and are unit-tested in isolation. Phase 12 proves they compose correctly — that the data flows from RepoExplorer through Coder through TestAgent through PRAgent and into the TUI without any wiring gaps. Hardening (Phase 13) then addresses the real failure modes found here rather than hypothetical ones.

**Q: What changes after this phase?**
The project has a working full-stack smoke test. Phase 13 can now systematically harden: timeout configuration, graceful shutdown, log overflow limits, error display. The E2E baseline also serves as a regression guard: if Phase 13 changes break agent wiring, these tests catch it.

**Q: What could break?**
- If any agent changes its `run()` signature, the full pipeline fixture fails without a clear message — the error surfaces in the Orchestrator's exception handler as `wm.state == FAILED`. Add `pytest.raises` guards if signatures are expected to change.
- `FakeTestRunner` returns a fixed string — if `parse_pytest_output` regex changes, the E2E tests may pass but unit `TestHappyPath::test_test_results_populated` would fail first.
- `FakeEditProvider` always returns the same edit regardless of what the RepoExplorer found. If `CoderAgent` changes its file-staging logic, the edit might target a path that isn't staged, causing `read_file` to raise `FileNotFoundError` inside the agent.

**Q: Why FakeTestRunner instead of running real pytest in the sandbox?**
Running real pytest in the sandbox would require the sandbox Python environment to have the test project's imports available. That means either installing the project into the sandbox or constructing a `sys.path`-aware command. `FakeTestRunner` removes the environment dependency while still exercising the full TestAgent state machine. The sandbox execute contract is already proven in Phase 5 unit tests (`test_sandbox_execute.py`).

**Q: Why is Phase 12 tests-only — no new source files?**
All source code was built in Phases 0–11. Phase 12's value is purely integration proof: the right data flows through the right seams. Adding source files here would be adding features, which belongs in a named phase.

**Q: Why place E2E tests in `tests/e2e/` without an `e2e` marker?**
The `e2e` marker in `pyproject.toml` is defined as "end-to-end against real GitHub". These tests use `FakeGitHub` — no real GitHub. Marking them `e2e` would exclude them from the default CI run, which is exactly wrong. They should run on every push. The `tests/e2e/` directory name signals scope without restricting execution.

## Decisions Log

| # | Decision | Alternatives considered | Rationale |
|---|---|---|---|
| 1 | `FakeTestRunner` not real subprocess pytest | Real pytest in sandbox | No environment setup needed; subprocess contract proven in Phase 5 |
| 2 | `FakeEditProvider` with pre-configured edits | Mock LLM API | Deterministic; no API key; fast |
| 3 | `FakeGitHub`/`FakeRepo` (existing from Phase 1) | New fake | Reuse established fakes; no duplication |
| 4 | `done_wm` fixture shared across `TestHappyPath` | One test per pipeline run | Single orchestrator run; 11 assertions on the same result; faster |
| 5 | No `e2e` marker on these tests | Mark with `integration` or `e2e` | Tests run with no external services; should execute in default CI |
| 6 | Source repo with real Python files | In-memory fake | Tests RepoExplorer's actual AST parsing; more realistic |

## Risks / Things to Revisit

- **FakeTestRunner hides real test failures**: The E2E tests prove wiring but not correctness of the code the Coder produces. A Phase 13 addition: one test where `SandboxTestRunner` runs real pytest on a tiny known-good fixture.
- **_TwoPhaseRunner is a bespoke test double**: The retry test uses an inline class. If the retry loop changes (e.g., the Orchestrator passes additional arguments to the runner), this double breaks silently. Consider promoting a `SequencedFakeTestRunner` to `_gh_fakes.py` or a test utilities module.
- **No concurrent task test**: `max_inflight_tasks > 1` (from Settings) is not tested. A thread-safety test with two concurrent `run_issue` calls on different `WorkingMemory` objects should be added when async support lands in Phase 13.
- **TUI test calls upsert_task synchronously**: In production, `call_from_thread` is required. The tests call `upsert_task` directly (they're already on the Textual event loop via `run_test`). This works but doesn't test the `call_from_thread` path. A future test should spawn a thread and use `call_from_thread` to confirm thread safety.
