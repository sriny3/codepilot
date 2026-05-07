# Phase 8 — Steering Doc: Test Agent

**Status:** complete
**Owner:** agents / quality
**Depends on:** Phase 5 (Sandbox — `LocalSandbox.execute`, `copy_subset`), Phase 2 (Memory — `WorkingMemory`, `TestRunSummary`), Phase 7 (Coder — populates sandbox with edits and `wm.proposed_diff`)
**Unblocks:** Phase 9 (PR Agent — checks `wm.test_results.failed == 0` before opening PR), Phase 10 (Orchestrator — drives retry loop: failed tests → back to IMPLEMENTING)

---

## Goal

Run the project test suite inside the sandbox and record the outcome in `WorkingMemory`. The Test Agent:

1. **Stages** any extra files (test files, fixtures, config) that weren't staged by the Coder.
2. **Runs** the test command via a pluggable `TestRunner` (default: `SandboxTestRunner`).
3. **Parses** the pytest terminal output into a `TestRunSummary` with pass/fail counts and per-failure details.
4. **Records** the summary in `wm.test_results`.
5. **Transitions** state from `IMPLEMENTING → TESTING`.

Like the Coder, the runner is injected — `FakeTestRunner` makes the agent fully testable without actually spawning pytest.

## Deliverables

| Artifact | Path | Purpose |
|---|---|---|
| Runner types | `codepilot/agents/test_agent/runner.py` | `RunConfig`, `TestRunner` (Protocol), `SandboxTestRunner`, `FakeTestRunner` |
| Output parser | `codepilot/agents/test_agent/parser.py` | `parse_pytest_output` |
| Agent | `codepilot/agents/test_agent/agent.py` | `TestAgent` |
| Public API | `codepilot/agents/test_agent/__init__.py` | Re-exports all public symbols |
| Parser tests | `tests/unit/test_test_parser.py` | 17 tests — counts, failure lines, framework detection |
| Runner tests | `tests/unit/test_test_runner.py` | 14 tests — fake double, sandbox runner contract |
| Agent tests | `tests/unit/test_test_agent.py` | 15 tests — state transitions, staging, command forwarding, results |

## Exit Criteria

- `parse_pytest_output` extracts `passed`, `failed`, failures list, and `framework`.
- Fallback: `exit_code != 0` with no parseable counts → `failed=1`.
- `FakeTestRunner` returns pre-configured result; records `last_command` and `last_timeout`; satisfies `TestRunner` protocol.
- `SandboxTestRunner` satisfies `TestRunner` protocol; delegates to `sandbox.execute`.
- `TestAgent.run` transitions `IMPLEMENTING → TESTING`; raises `InvalidTransition` from TRIAGED or EXPLORING.
- `extra_files` staged from `source_root` before test run; no staging when list is empty.
- `wm.test_results` populated with correct pass/fail counts and failure details.
- `pytest` green: 700 passed, 2 skipped.

## Files

### Source

#### `codepilot/agents/test_agent/runner.py`

**`RunConfig`** — plain dataclass: `command: str`, `extra_files: list[str]` (default `[]`), `timeout: float` (default `120.0`).

**`TestRunner`** — `@runtime_checkable` Protocol:
```python
def run(self, sandbox, *, command: str, timeout: float) -> ExecuteResult: ...
```
No `__test__ = False` — setting it on the Protocol would make it part of the interface (implementors would need it too, breaking `isinstance` checks). pytest skips collection because `TestRunner` has no `test_*` methods; a `PytestCollectionWarning` was silenced via `pyproject.toml` `-W ignore::pytest.PytestCollectionWarning`.

**`SandboxTestRunner`** — delegates directly to `sandbox.execute(command, timeout=timeout)`.

**`FakeTestRunner`** — deterministic double: pre-configure `stdout`, `stderr`, `exit_code`, `duration_ms`. Records `last_command` and `last_timeout` for assertion.

#### `codepilot/agents/test_agent/parser.py`

**`parse_pytest_output(stdout, stderr, exit_code) → TestRunSummary`**:

1. Searches combined `stdout + "\n" + stderr` for `_PASSED_RE` (`"(\d+) passed"`) and `_FAILED_RE` (`"(\d+) (failed|error)"`).
2. If neither found and `exit_code != 0` → `failed = 1` (process crashed, collection error, etc.).
3. Extracts per-failure lines with `_FAILURE_LINE_RE`: `"^FAILED \S+ - .+$"` → `{"test": ..., "reason": ...}`.
4. Detects `framework = "pytest"` when `"pytest"` (case-insensitive), `"PASSED"`, or `"FAILED"` appears in output.

#### `codepilot/agents/test_agent/agent.py`

**`TestAgent`** (has `__test__ = False` to prevent pytest collection):
- `__init__(sandbox, source_root, *, runner=None)` — `runner=None` constructs `SandboxTestRunner()`.
- `run(wm, config)`:
  1. `wm.transition(TaskState.TESTING)`.
  2. `sandbox.copy_subset(source_root, config.extra_files)` if non-empty.
  3. `runner.run(sandbox, command=config.command, timeout=config.timeout)`.
  4. `parse_pytest_output(result.stdout, result.stderr, result.exit_code)`.
  5. `wm.test_results = summary`.
  6. Emit `Event.TESTS_RUN`.
  7. Return `wm`.

#### `codepilot/agents/test_agent/__init__.py`

Re-exports: `FakeTestRunner`, `RunConfig`, `SandboxTestRunner`, `TestAgent`, `TestRunner`, `parse_pytest_output`.

### Tests

#### `tests/unit/test_test_parser.py` (17 tests)

One class `TestParseOutput`:

- `"5 passed"` → `passed=5, failed=0`.
- `"3 passed, 2 failed"` → `passed=3, failed=2`.
- `"1 error"` → `failed=1`.
- `"2 passed, 1 error"` → `passed=2, failed=1`.
- Empty output + `exit_code=0` → `passed=0, failed=0`.
- Empty output + `exit_code=1` → `failed=1` (fallback).
- Two `FAILED` lines → `failures` list length 2.
- `FAILED tests/foo.py::test_bar` → `failures[0]["test"]` correct.
- Reason extracted from `FAILED` line.
- Framework detected from `"pytest"` keyword, `"FAILED"` marker, `"PASSED"` marker.
- Framework `None` when no hints.
- Returns `TestRunSummary` type.
- `stderr` also parsed.
- No failures when all pass.
- Single `FAILED` line (no summary line) still extracts failure.

#### `tests/unit/test_test_runner.py` (14 tests)

Two classes:

- `TestFakeTestRunner` (10) — stdout/stderr/exit_code configured; `last_command`/`last_timeout` recorded; returns `ExecuteResult`; default exit_code=0; satisfies protocol; `SandboxTestRunner` satisfies protocol.
- `TestSandboxTestRunnerContract` (4) — actual subprocess: stdout captured, exit_code propagated, `duration_ms >= 0`, returns `ExecuteResult`.

#### `tests/unit/test_test_agent.py` (15 tests)

One class `TestTestAgent`:

- Transitions to TESTING; results populated; `passed`/`failed` counts; failure details; command forwarded; timeout forwarded; `extra_files` staged; no staging when empty; returns same `wm`; `InvalidTransition` from TRIAGED; `InvalidTransition` from EXPLORING; default runner is `SandboxTestRunner`; zero failed on all-pass output; framework recorded.

## Architecture

```
TestAgent.run(wm, RunConfig)
    │
    ├─► wm.transition(TESTING)
    │
    ├─► sandbox.copy_subset(source_root, config.extra_files)
    │       (skipped if extra_files is empty)
    │
    ├─► runner.run(sandbox, command=…, timeout=…)
    │       ├── FakeTestRunner   (tests — returns pre-configured result)
    │       └── SandboxTestRunner  (prod — delegates to sandbox.execute)
    │
    ├─► parse_pytest_output(stdout, stderr, exit_code)
    │       ├─► _PASSED_RE / _FAILED_RE → counts
    │       ├─► _FAILURE_LINE_RE → failures list
    │       ├─► exit_code fallback → failed=1
    │       └─► framework detection
    │
    ├─► wm.test_results = TestRunSummary(…)
    │
    └─► log Event.TESTS_RUN
```

## FAQ

**Q: Why parse pytest output rather than using the pytest Python API?**
The sandbox runs commands as subprocesses — the test suite might use a different Python environment, virtualenv, or interpreter. Parsing terminal output is framework-agnostic and works regardless of whether the sandbox has pytest installed as a library. It also handles `unittest`, `nose`, and any tool that emits `N passed` / `N failed` summary lines.

**Q: Why does `TestRunner` not have `__test__ = False`?**
Setting a class attribute on a `@runtime_checkable` Protocol makes it part of the protocol interface — all implementors would need that attribute for `isinstance` to return `True`. Without it on `FakeTestRunner` and `SandboxTestRunner`, the protocol check fails. The warning was suppressed globally in `pyproject.toml` since no legitimate test class is named `TestRunner`.

**Q: Why does `TestAgent` have `__test__ = False`?**
`TestAgent` starts with `"Test"` — pytest tries to collect it. Unlike `TestRunner` (Protocol, which has an implicit `__init__` from `Protocol`), `TestAgent` has an explicit `__init__` with required arguments, so pytest's collection would fail noisily. `__test__ = False` suppresses collection without affecting the class's behaviour.

**Q: Why is the default timeout 120 seconds?**
Most unit test suites finish in under 30 seconds, but integration suites can run for minutes. 120s is a safe default that avoids hanging the pipeline while still allowing longer suites. Callers can pass a shorter timeout via `RunConfig(timeout=30.0)`.

**Q: Why does the parser use `exit_code` as a fallback rather than trusting only the output?**
Pytest can fail to produce any summary output when there's a collection error (import error, conftest crash, etc.) or when it's killed by a signal. In those cases, `exit_code != 0` is the only signal. Recording `failed=1` ensures `wm.test_results.failed > 0` so the Orchestrator's retry logic fires.

**Q: Why does `extra_files` exist — shouldn't all files be staged by the Coder?**
The Coder stages only `wm.relevant_files` (files to be edited). Test files, fixtures, and test config (`conftest.py`, `pytest.ini`) are not being edited and so aren't in `relevant_files`. The Test Agent needs them to run the suite. `extra_files` is the explicit handoff point.

**Q: Why is `source_root` in the constructor rather than in `run`?**
It never changes between runs for a given task. Passing it at construction time keeps the `run` signature minimal — the Orchestrator constructs one `TestAgent` per task and calls `run` potentially multiple times (retry loop). Passing `source_root` to every `run` call would be redundant noise.

## Decisions Log

| # | Decision | Alternatives considered | Rationale |
|---|---|---|---|
| 1 | Parse terminal output | pytest Python API | Subprocess isolation; framework-agnostic; works across Python envs |
| 2 | `exit_code` fallback → `failed=1` | Raise on unparseable output | Collection errors must not silently pass; retry loop must fire |
| 3 | `TestRunner` Protocol, no `__test__=False` | Rename to `RunnerProtocol` | Name `TestRunner` is intuitive; warning suppressed globally |
| 4 | `TestAgent.__test__ = False` | Rename to `AgentUnderTest` | Name is correct; `__test__=False` is the standard suppression idiom |
| 5 | `extra_files` in `RunConfig` | Second `copy_subset` call outside agent | Encapsulates staging decision in config; agent owns all sandbox setup |
| 6 | `source_root` in constructor | Pass per `run` call | Never changes per task; keeps `run` signature clean |

## Risks / Things to Revisit

- **Non-pytest frameworks**: The parser understands pytest summary lines (`N passed`, `N failed`, `FAILED ...`). `unittest` and `jest` have different output formats. Add separate parsers and auto-detect from `RunConfig.command` when supporting multi-framework repos.
- **Collection errors hide real failures**: A pytest collection error with `exit_code=2` triggers the `failed=1` fallback. The Orchestrator sees `failed=1` and retries the Coder. The real problem is the import error in the test file — the Coder should fix it. This works but produces one spurious retry. A future improvement: detect collection errors and surface a different error code.
- **Timeout too generous for fast suites**: 120s default may let a hanging test run waste the orchestrator's time. The `RunConfig` should be driven from `settings.py` in Phase 10.
- **No stderr in failures list**: Failure reasons are extracted from `FAILED` lines in stdout. Long tracebacks are not included. For the PR description, the Orchestrator may want to include the full failure block — capture it with a regex spanning multiple lines in a future enhancement.
