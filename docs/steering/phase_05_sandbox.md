# Phase 5 — Steering Doc: Sandbox Execution

**Status:** complete
**Owner:** platform / execution
**Depends on:** Phase 4 (Guardrails — `ShellGuard` wired into every `execute` call), Phase 0.5 (Logging — `Event.SANDBOX_EXECUTE` audit events)
**Unblocks:** Phase 6 (Repo Explorer — reads files through sandbox), Phase 7 (Coder — writes and runs code inside sandbox), Phase 8 (Test Agent — runs test suites via `execute`), Phase 12 (E2E — full agent loop exercises sandbox path)

---

## Goal

Give every agent a **contained execution environment** with three hard guarantees:

1. **Path containment** — no file operation can read, write, or delete outside the sandbox root, regardless of `../` traversal, symlinks, or absolute paths.
2. **Command guardrails** — every shell command is pre-screened by `ShellGuard`; blocked commands raise `PermissionError` before a subprocess is spawned.
3. **Deterministic diffing** — changes made inside the sandbox can be serialised as a unified diff and applied back to the source tree, with no external `patch` binary required.

The sandbox is a **pure local** implementation (`LocalSandbox`). It uses only the standard library (`pathlib`, `subprocess`, `difflib`, `shutil`) so it works on Windows, macOS, and Linux without any Docker or container runtime.

## Deliverables

| Artifact | Path | Purpose |
|---|---|---|
| Core sandbox | `codepilot/sandbox/local.py` | `LocalSandbox`, `SandboxEscapeError`, `ExecuteResult`, `ExecuteTimeout` |
| Diff utilities | `codepilot/sandbox/diff.py` | `generate_diff_from_content`, `generate_diff`, `generate_sandbox_diff`, `apply_diff`, `_apply_hunks` |
| Public API | `codepilot/sandbox/__init__.py` | Re-exports all public symbols |
| Redaction helper | `codepilot/observability/redaction.py` | Added `redact_cmd` — strips secrets, truncates long commands for structured logs |
| Isolation tests | `tests/unit/test_sandbox_isolation.py` | Path containment (write/read/delete/exists/symlink/absolute paths) |
| Execute tests | `tests/unit/test_sandbox_execute.py` | stdout/stderr capture, exit codes, timeout, cwd, guardrail enforcement |
| Copy/list tests | `tests/unit/test_sandbox_subset.py` | `copy_subset` filtering/structure/overwrite, `list_files` relative paths/glob |
| Diff tests | `tests/unit/test_diff_gen.py` | `generate_diff_from_content`, file-based diff, sandbox diff, `apply_diff` round-trips |

## Exit Criteria

- `SandboxEscapeError` raised for `../` traversal, `../../` traversal, absolute paths outside root, and symlinks pointing outside (posix only).
- `exists()` swallows `SandboxEscapeError` and returns `False` (safe sentinel, not an error).
- `execute` pre-checks `ShellGuard`; both BLOCK and HITL decisions raise `PermissionError` before any subprocess starts.
- `ExecuteTimeout` raised when command exceeds `timeout` seconds; `.cmd` and `.timeout` attributes populated.
- `copy_subset` copies only requested files, skips missing files silently, preserves nested directory structure, overwrites on re-copy.
- `list_files()` returns empty list for empty sandbox; all paths are relative; supports glob patterns.
- `generate_diff_from_content` returns `""` for identical content; otherwise produces a valid unified diff with `---`/`+++` headers and `@@` hunk markers.
- `apply_diff` is a lossless round-trip: `original → diff → apply → modified` equals `modified` for single-hunk and multi-hunk diffs.
- `pytest` green: 562 passed, 2 skipped (symlink tests on Windows requiring elevated privileges).

## Files

### Source

#### `codepilot/sandbox/local.py`

Core containment and execution module. Four exports:

**`SandboxEscapeError(PermissionError)`** — raised whenever a path resolves outside `sandbox.root`. Carries `.path` (the offending path) and `.root` (sandbox root) for caller diagnostics. Subclasses `PermissionError` so callers that catch `PermissionError` get both escape errors and guardrail blocks from a single except clause.

**`ExecuteTimeout(TimeoutError)`** — raised when subprocess exceeds the timeout. Carries `.cmd` (original command string) and `.timeout` (seconds). Subclasses `TimeoutError` for straightforward `except TimeoutError` compatibility.

**`ExecuteResult`** — frozen dataclass: `stdout: str`, `stderr: str`, `exit_code: int`, `duration_ms: int`. `.success` property returns `exit_code == 0`.

**`LocalSandbox`** — the main class:
- `__init__(root, *, shell_guard=None, audit=None, agent="sandbox")` — creates sandbox at `root`; if `shell_guard` is `None`, constructs a default `ShellGuard()`.
- `_safe_path(path)` — resolves path relative to root, calls `.relative_to(root)` to verify containment, raises `SandboxEscapeError` on escape. Handles both relative and absolute inputs.
- `write_file(path, content)` — creates parent directories, writes UTF-8 text.
- `read_file(path)` — reads UTF-8 text.
- `delete_file(path)` — unlinks file.
- `exists(path)` — containment-safe existence check; returns `False` on `SandboxEscapeError`.
- `list_files(pattern="**/*")` — returns sorted relative `Path` objects matching the glob pattern; files only (no directories).
- `copy_subset(source_root, files)` — copies each named file from `source_root` to the sandbox preserving structure; silently skips non-existent source files.
- `execute(cmd, *, timeout=30.0, cwd=None, env=None)` — pre-checks `ShellGuard`; BLOCK raises `PermissionError` immediately; HITL also raises `PermissionError` (sandbox never does interactive approval — that's the orchestrator's job); spawns subprocess with `shell=True, capture_output=True`; records `duration_ms`; emits `Event.SANDBOX_EXECUTE` structlog event with redacted command; raises `ExecuteTimeout` on timeout.

#### `codepilot/sandbox/diff.py`

Pure-Python diff generation and application. No external `patch` binary needed.

**`generate_diff_from_content(original, modified, *, label_a, label_b, context_lines=3)`** — wraps `difflib.unified_diff`. Returns `""` when content is identical (no lines differ). Otherwise returns the full unified diff string including `---`/`+++` headers and `@@` hunk markers.

**`generate_diff(original: Path, modified: Path, **kwargs)`** — reads both files (treats non-existent `original` as empty string) then delegates to `generate_diff_from_content`. Default labels use file names.

**`generate_sandbox_diff(sandbox, source_root, files, *, context_lines=3)`** — diffs each tracked file between `source_root` and the sandbox. Concatenates per-file diffs; files with no changes contribute nothing. Useful for summarising all changes an agent made.

**`_apply_hunks(original_lines, diff_text)`** — pure-Python unified diff applier. Parses `@@` headers via `_HUNK_RE`. Tracks a cumulative line offset as each hunk shifts the file. For each hunk: copies context lines from original, applies `+` insertions and skips `-` deletions, copies remaining original tail. Does not shell out.

**`apply_diff(target: Path, diff_text: str)`** — reads target, calls `_apply_hunks`, writes result back atomically. No-op when `diff_text` is blank.

#### `codepilot/sandbox/__init__.py`

Re-exports: `ExecuteResult`, `ExecuteTimeout`, `LocalSandbox`, `SandboxEscapeError`, `apply_diff`, `generate_diff`, `generate_diff_from_content`, `generate_sandbox_diff`.

#### `codepilot/observability/redaction.py` (addition)

Added `redact_cmd(cmd, max_len=200)` — pipes the command string through the existing `_scrub_str` scrubber (strips tokens matching secret patterns), then truncates with `…` ellipsis if still over `max_len`. Used by `LocalSandbox.execute` before emitting the structlog event so secrets in curl headers or env-injection commands never reach log sinks.

### Tests

#### `tests/unit/test_sandbox_isolation.py` (27 tests)

Containment contract. Six test classes:

- `TestWriteContainment` — nested writes succeed; `../` traversal raises `SandboxEscapeError`.
- `TestReadContainment` — reads inside sandbox succeed; traversal raises.
- `TestAbsolutePathContainment` — absolute path inside sandbox accepted; absolute path outside raises.
- `TestSymlinkContainment` — decorated `@pytest.mark.skipif(sys.platform == "win32", ...)` because symlink creation requires elevated privileges on Windows. Symlink to outside raises; symlink within sandbox resolves correctly.
- `TestDeleteContainment` — delete within succeeds; traversal raises.
- `TestExistsContainment` — `exists` returns `False` for escaping paths (not an error).
- `TestSandboxEscapeError` — `.root` and `.path` attributes populated; `isinstance(exc, PermissionError)` true.

#### `tests/unit/test_sandbox_execute.py` (24 tests)

Execution contract. Five test classes:

- `TestBasicExecution` — stdout captured, stderr captured, exit codes 0/1/42, both streams simultaneously.
- `TestExecuteResult` — `isinstance(result, ExecuteResult)`, `duration_ms >= 0`, `success` property.
- `TestTimeout` — `ExecuteTimeout` raised with `.timeout` and `.cmd` populated; fast command does not timeout; `isinstance(exc, TimeoutError)` true.
- `TestCwd` — defaults to sandbox root; `cwd="sub"` subdir works; `cwd="../../outside"` raises `SandboxEscapeError`.
- `TestGuardrailEnforcement` — fork-bomb blocked; `rm -rf` HITL-blocked; custom extra-rule blocks `echo`; benign command passes; error messages include rule name / approval hint.

All subprocess commands use `python -c "..."` pattern for Windows compatibility (avoids `sleep`, `echo`, `cat` differences).

#### `tests/unit/test_sandbox_subset.py` (17 tests)

`copy_subset` and `list_files`. Four test classes:

- `TestCopySubsetFiltering` — only listed files present; unlisted absent; all files copied when all listed.
- `TestCopySubsetStructure` — nested paths preserved; content identical to source; `list_files` shows staged files.
- `TestCopySubsetMissingFiles` — missing file skipped silently; all missing leaves sandbox empty; empty list leaves sandbox empty.
- `TestCopySubsetOverwrite` — second copy overwrites; independently written file survives unrelated copy.
- `TestListFiles` — empty sandbox returns `[]`; all paths relative; glob pattern filters by extension.

Source fixture creates `secrets/.env` as a **directory** (not a file) to verify the sandbox skips non-file paths naturally.

#### `tests/unit/test_diff_gen.py` (27 tests)

Diff generation and application. Four test classes:

- `TestGenerateDiffFromContent` — identical → `""`; unified header; hunk `@@`; `+`/`-` marking; context lines; custom labels; empty original → pure addition; empty modified → pure deletion; multi-line change.
- `TestGenerateDiff` — identical files → `""`; matches `generate_diff_from_content` variant; non-existent original treated as empty.
- `TestGenerateSandboxDiff` — modified file in diff; unchanged file absent from diff; no changes → `""`; new file appears as addition; diff has `---`/`+++`/`@@`.
- `TestApplyDiff` — apply addition; apply deletion; apply replacement; empty diff is no-op; round-trip (`original → diff → apply == modified`); multi-hunk diff (two non-adjacent changes).

## Architecture

```
Agent tool call
      │
      ▼
LocalSandbox.execute(cmd)
      │
      ├─► ShellGuard.validate(cmd) ──► BLOCK/HITL → PermissionError (no subprocess)
      │
      ▼
subprocess.run(shell=True, cwd=sandbox_root/cwd, timeout=timeout)
      │
      ├─► TimeoutExpired → ExecuteTimeout
      │
      └─► ExecuteResult(stdout, stderr, exit_code, duration_ms)
              │
              └─► structlog.info(Event.SANDBOX_EXECUTE, cmd=redact_cmd(cmd), ...)


LocalSandbox.{read,write,delete}_file(path)
      │
      └─► _safe_path(path)
              │
              ├─► Path.resolve().relative_to(root) → OK
              └─► raises SandboxEscapeError


generate_sandbox_diff(sandbox, source_root, files)
      │
      └─► for each file: generate_diff(source_root/f, sandbox.root/f)
                └─► generate_diff_from_content(...)   [difflib.unified_diff]


apply_diff(target, diff_text)
      │
      └─► _apply_hunks(target.read_text().splitlines(), diff_text)
              └─► parse @@ headers → apply +/-/context lines → write back
```

## FAQ

**Q: Why `shell=True` in subprocess instead of shlex.split?**
Shell expansion is what agents actually need — they pass commands like `python -m pytest tests/` or `pip install -r requirements.txt`, which require a shell. ShellGuard runs before the subprocess, so the risk of shell injection is mitigated by the allow-list approach rather than by avoiding the shell entirely.

**Q: Why does HITL decision also raise `PermissionError` in the sandbox?**
The sandbox is a non-interactive component. It cannot block waiting for human input — that's the orchestrator's responsibility. When the sandbox sees HITL, it raises `PermissionError` so the orchestrator can catch it, present the approval UI, and retry the operation if approved. The HITL gate backends (`ConsoleHitlGate`, etc.) live in the guardrails layer, not the sandbox.

**Q: Why pure-Python diff applier instead of `subprocess(['patch', ...])`?**
`patch` is not reliably available on Windows without Git-for-Windows or MSYS2. The agents must work in a clean Windows dev environment. `difflib` is stdlib. The `_apply_hunks` implementation handles the realistic diff shapes the project generates (context lines, multi-hunk, empty files) with a straightforward offset-tracking algorithm.

**Q: Why does `exists()` return `False` on escape instead of raising?**
Callers use `exists()` as a boolean guard before operations. If it raised, every caller would need a try/except around what is conceptually a predicate call. Returning `False` is semantically correct — from the sandbox's perspective, a path outside the root does not exist in its namespace.

**Q: Why `copy_subset` instead of copying the whole source tree?**
Agents receive a targeted list of files from the planner (e.g. "edit `src/auth.py` and `tests/test_auth.py`"). Copying only those files keeps the sandbox small, avoids staging secrets that exist in the real repo, and makes the resulting diff focused on the agent's actual changes.

**Q: Why skip symlink tests on Windows?**
`os.symlink` requires `SeCreateSymbolicLinkPrivilege`, which is not granted to standard user accounts even in admin-level dev sessions. Skipping the tests on Windows with `@pytest.mark.skipif(sys.platform == "win32", ...)` is the standard pytest idiom for platform-specific filesystem features.

**Q: Why `duration_ms: int` rather than `float`?**
Millisecond integer is the standard unit in structlog events and OpenTelemetry spans. `int` avoids floating-point representation noise in logs. Sub-millisecond precision is not meaningful for subprocess durations.

**Q: Why does `_safe_path` call `.resolve()` before `.relative_to()`?**
`.resolve()` canonicalises symlinks and `..` components, so a path like `sandbox_root/sub/../../../etc/passwd` becomes `/etc/passwd` before the containment check. Without `.resolve()`, a crafted relative path could bypass the check.

**Q: Why `generate_diff_from_content` return `""` for identical content rather than a header-only diff?**
`difflib.unified_diff` returns an empty iterator when inputs are identical, so `"".join(...)` naturally produces `""`. The empty-string contract is useful: callers can check `if diff:` to skip apply operations, and `generate_sandbox_diff` uses it to omit unchanged files from the aggregate diff.

**Q: Why structlog `info` (not `debug`) for `SANDBOX_EXECUTE` events?**
Execute events are the primary audit trail for what agents did. Operators need them at `info` level in production so they appear in monitoring dashboards without enabling debug logging. Debug level would hide them in deployed environments.

## Decisions Log

| # | Decision | Alternatives considered | Rationale |
|---|---|---|---|
| 1 | Pure-Python `_apply_hunks` | `subprocess patch`; `python-patch` PyPI package | No external binary needed on Windows; no extra dependency; realistic diff shapes are simple enough to implement reliably |
| 2 | `shell=True` in subprocess | `shlex.split` + `shell=False` | Agents generate shell commands, not argv lists; ShellGuard pre-screening is the safety layer |
| 3 | HITL raises `PermissionError` in sandbox | Block caller silently; return special `ExecuteResult` | Orchestrator must own the approval UX; raising makes the contract explicit and testable |
| 4 | `exists()` swallows `SandboxEscapeError` → `False` | Re-raise; return `None` | Boolean predicate API; caller code reads `if sandbox.exists("f"):` without try/except |
| 5 | `copy_subset` skips missing files silently | Raise on first missing file; warn | Planner may list files it expects to exist post-creation; silent skip lets the agent create them fresh |
| 6 | Symlink tests skipped on Windows | Run with `pytest-anyio` elevated fixture; skip entire class | Standard platform skip idiom; tests run in CI on Linux where symlinks work |
| 7 | `duration_ms: int` | `float`; `timedelta` | Matches structlog/OTel conventions; no sub-ms precision needed |
| 8 | `redact_cmd` truncates at 200 chars | No truncation; 500 chars | Log lines stay readable; commands are often repetitive past 200 chars |

## Risks / Things to Revisit

- **Windows `shell=True` injection surface**: ShellGuard is the primary mitigation. If an agent can influence the command string with user-supplied data, a ShellGuard bypass could lead to code execution. Revisit when adding web-fetched content to commands.
- **`_apply_hunks` edge cases**: The pure-Python applier handles the diff shapes `difflib` generates. It has not been tested against diffs produced by external tools (git, GNU diff) — those may use extended headers or `\ No newline at end of file` markers that the parser ignores. If the Coder agent ingests external patches, add regression tests.
- **Sandbox cleanup**: `LocalSandbox` creates files but never deletes the root directory. The orchestrator is responsible for cleanup. If agents crash mid-run, temp directories accumulate. Consider a context manager interface (`__enter__`/`__exit__`) in a future phase.
- **`shell=True` on Windows uses cmd.exe**: `python -c "..."` commands work cross-platform, but agent-generated commands targeting bash-isms (`&&`, pipes, `$VAR`) may fail silently on Windows. Log the exit code and stderr; surface failures clearly.
- **No stdin support**: `execute` does not wire stdin. Commands that prompt for input will hang until timeout. Document this constraint for Phase 7 (Coder) so it avoids interactive commands (e.g., `pip install` with confirmation prompts — use `-y` flags).
