# Phase 7 — Steering Doc: Coder Agent

**Status:** complete
**Owner:** agents / code-generation
**Depends on:** Phase 5 (Sandbox — `LocalSandbox`, `generate_sandbox_diff`), Phase 4 (Guardrails — `FileGuard`), Phase 2 (Memory — `WorkingMemory`, state transitions), Phase 6 (Repo Explorer — populates `wm.relevant_files` and `wm.repo_map_path`)
**Unblocks:** Phase 8 (Test Agent — runs tests against the edits recorded in `wm.proposed_diff`), Phase 9 (PR Agent — uses `wm.proposed_diff` to open the PR), Phase 10 (Orchestrator — drives `CoderAgent.run` after `RepoExplorerAgent`)

---

## Goal

Apply generated code edits to the sandbox and produce a verified unified diff. The Coder agent:

1. **Stages** the relevant source files into the sandbox.
2. **Collects** their current content as a structured dict for the edit provider.
3. **Calls** an `EditProvider` to get the list of file changes (without prescribing how edits are generated — LLM, rule engine, or test fake all satisfy the protocol).
4. **Guards** each edit against the `FileGuard` deny-list before writing.
5. **Records** the unified diff of all changes in `wm.proposed_diff`.

The agent is intentionally **thin**: it owns orchestration and side-effect application; the edit generation strategy is fully pluggable via the `EditProvider` protocol.

## Deliverables

| Artifact | Path | Purpose |
|---|---|---|
| Edit types | `codepilot/agents/coder/edits.py` | `FileEdit`, `EditProvider` protocol, `FakeEditProvider` |
| Agent | `codepilot/agents/coder/agent.py` | `CoderAgent` |
| Public API | `codepilot/agents/coder/__init__.py` | Re-exports all public symbols |
| Edit tests | `tests/unit/test_coder_edits.py` | `FileEdit` and `FakeEditProvider` (16 tests) |
| Agent tests | `tests/unit/test_coder_agent.py` | `CoderAgent.run` integration (18 tests) |

## Exit Criteria

- `FileEdit` is a frozen dataclass with `path` and `content`; equality by value.
- `FakeEditProvider` returns pre-configured edits; records last call arguments; copies `file_contents` dict to avoid aliasing; satisfies `EditProvider` protocol (runtime-checkable).
- `CoderAgent.run` transitions `EXPLORING → IMPLEMENTING` (or `IMPLEMENTING → IMPLEMENTING` for retries); raises `InvalidTransition` from TRIAGED.
- Staged files appear in sandbox before provider is called.
- `file_contents` dict passed to provider contains current file text from sandbox.
- `repo_map_path` content read from sandbox and passed as `repo_map`; empty string when not set.
- `FileGuard` blocks writes to `.env`, `*.key`, etc.; custom guards with extra rules work.
- After edits applied: `wm.proposed_diff` is a non-empty unified diff string showing `---`/`+++`/`@@` for changed files; empty string when no edits.
- New files (absent from source) appear as pure additions in the diff.
- Multiple edits all written; all appear in diff.
- `pytest` green: 654 passed, 2 skipped (symlink on Windows).

## Files

### Source

#### `codepilot/agents/coder/edits.py`

**`FileEdit`** — frozen dataclass: `path: str` (sandbox-relative, forward slashes), `content: str` (complete new file content, not a patch). Equality by value so tests can assert `result == edits`.

**`EditProvider`** — `@runtime_checkable` Protocol with one method:
```python
def generate_edits(
    self, *,
    issue_body: str,
    repo_map: str,
    file_contents: dict[str, str],
    skill_prompt: str | None = None,
) -> list[FileEdit]: ...
```
Any class implementing this method satisfies the protocol at runtime (`isinstance(obj, EditProvider)` → True). Future implementations: `LLMEditProvider` (OpenAI/Anthropic), `RuleEditProvider` (deterministic patterns).

**`FakeEditProvider`** — deterministic test double:
- `__init__(edits=None)` — accepts a pre-baked list; records last call arguments.
- `generate_edits(…)` — stores all four keyword args as `last_*` attributes (copies `file_contents` so mutation of the caller's dict doesn't corrupt the recorded snapshot). Returns a copy of `_edits`.

#### `codepilot/agents/coder/agent.py`

**`CoderAgent`**:
- `__init__(sandbox, edit_provider, *, file_guard=None)` — `file_guard=None` constructs a default `FileGuard()`.
- `run(wm, source_root, issue_body, *, skill_prompt=None)`:
  1. `wm.transition(TaskState.IMPLEMENTING)` — raises `InvalidTransition` on bad edge.
  2. `sandbox.copy_subset(source_root, wm.relevant_files)` — stage files.
  3. Read each `wm.relevant_files` path from sandbox; missing → `""`.
  4. Read `wm.repo_map_path` from sandbox if set and present; else `""`.
  5. `edit_provider.generate_edits(issue_body=…, repo_map=…, file_contents=…, skill_prompt=…)`.
  6. For each `FileEdit`: `guard.validate_path(edit.path)` → `BLOCK` raises `PermissionError`; else `sandbox.write_file(edit.path, edit.content)`.
  7. Emit `Event.EDIT_APPLIED` per written file.
  8. `all_tracked = order-preserving dedup(wm.relevant_files + edited_paths)`.
  9. `wm.proposed_diff = generate_sandbox_diff(sandbox, source_root, all_tracked)`.
  10. Return `wm`.

#### `codepilot/agents/coder/__init__.py`

Re-exports: `CoderAgent`, `EditProvider`, `FakeEditProvider`, `FileEdit`.

### Tests

#### `tests/unit/test_coder_edits.py` (16 tests)

Two test classes:

- `TestFileEdit` (5) — path/content stored, frozen (assignment raises), equality, inequality on path, inequality on content.
- `TestFakeEditProvider` (11) — returns configured edits, no edits by default, records issue_body/repo_map/file_contents/skill_prompt, file_contents copied not aliased, satisfies protocol, multiple edits, last call overwritten on second call.

#### `tests/unit/test_coder_agent.py` (18 tests)

One test class `TestCoderAgentRun`:

- State transitions to IMPLEMENTING; TRIAGED raises `InvalidTransition`; IMPLEMENTING→IMPLEMENTING retry valid.
- Edit written to sandbox; `wm.proposed_diff` populated and non-empty.
- Diff shows removed and added lines; no edits → empty diff.
- `issue_body`, `file_contents`, `skill_prompt`, `repo_map_text` all correctly forwarded to provider.
- New file (not in source) appears as pure addition in diff.
- `FileGuard` blocks `.env` write; custom guard blocks custom pattern.
- Missing source file → pure addition; multiple edits all written; returns same `wm` object.

## Architecture

```
Orchestrator
    │
    └─► CoderAgent.run(wm, source_root, issue_body, skill_prompt=…)
            │
            ├─► wm.transition(IMPLEMENTING)
            │
            ├─► sandbox.copy_subset(source_root, wm.relevant_files)
            │
            ├─► read file_contents from sandbox
            │   (missing files → "")
            │
            ├─► read repo_map from sandbox (if wm.repo_map_path set)
            │
            ├─► edit_provider.generate_edits(…)  ◄── pluggable
            │       ├── FakeEditProvider (tests)
            │       ├── LLMEditProvider (prod: OpenAI / Anthropic)
            │       └── RuleEditProvider (future)
            │
            ├─► for each FileEdit:
            │       ├─► FileGuard.validate_path(edit.path)  → BLOCK → PermissionError
            │       └─► sandbox.write_file(edit.path, edit.content)
            │               └─► log Event.EDIT_APPLIED
            │
            ├─► generate_sandbox_diff(sandbox, source_root, all_tracked)
            │
            └─► wm.proposed_diff = diff_text
```

## FAQ

**Q: Why `EditProvider` as a Protocol instead of an ABC?**
Protocols allow structural subtyping — any object with a `generate_edits` method satisfies it without inheriting from a base class. This means third-party LLM libraries or custom wrappers can be passed directly without modification. `@runtime_checkable` enables `isinstance` checks for defensive assertions in tests.

**Q: Why does `FileEdit.content` hold full file content rather than a diff?**
Diffs require parsing and application logic (which we already have in `apply_diff`). Full content is simpler: the provider writes the complete new file, and `generate_sandbox_diff` produces the diff against the source automatically. No double-parsing. The tradeoff is slightly larger payloads for large files, but for typical code files this is irrelevant.

**Q: Why does `CoderAgent` read `file_contents` from sandbox (post-copy) rather than from source_root directly?**
The sandbox copy may differ from source if a previous retry already wrote partial edits. Reading from the sandbox ensures the provider sees the current state, not the original. On first run, they're identical.

**Q: Why does `FileGuard` default to `FileGuard()` (builtin rules) if none is passed?**
The built-in rules block `.env`, `*.pem`, SSH keys, etc. — these should always be enforced. Requiring callers to construct and pass a guard explicitly would be easy to forget. The default makes the safe behaviour the default.

**Q: Why is `skill_prompt=None` the default rather than passing it from `wm.task_type`?**
The skill system lives in Phase 3 and needs a `SkillsRegistry` lookup to produce the prompt text. The Coder agent doesn't own that lookup — the Orchestrator does. The Orchestrator renders the skill prompt and passes it in. The agent is skill-agnostic.

**Q: Why does the diff use `all_tracked = dedup(relevant_files + edited_paths)` rather than just `edited_paths`?**
If an edit provider returns no edits for a file, `edited_paths` won't contain it — but if it was staged from source and already existed, it's still "tracked". By including `wm.relevant_files`, unchanged files produce empty diffs (which `generate_sandbox_diff` omits), and the overall diff is still correct. New files added by the provider appear at the end.

**Q: Why `PermissionError` (not a custom exception) for file guard blocks?**
Consistency with `SandboxEscapeError` and guardrail blocks — both are `PermissionError` subclasses. The orchestrator can catch `PermissionError` once and handle all permission-related failures uniformly.

## Decisions Log

| # | Decision | Alternatives considered | Rationale |
|---|---|---|---|
| 1 | `EditProvider` as `@runtime_checkable` Protocol | ABC with abstract method | Structural subtyping; no inheritance required for third-party LLM wrappers |
| 2 | `FileEdit.content` = full content | Diff/patch string | Simpler; `generate_sandbox_diff` produces the diff for free |
| 3 | `FakeEditProvider` records last call | Mock library (pytest-mock) | Zero extra dependency; explicit test assertions without mock setup overhead |
| 4 | FileGuard default = `FileGuard()` | Require caller to pass guard | Safe-by-default; forgetting to pass a guard still blocks `.env` writes |
| 5 | `all_tracked` = dedup(relevant ∪ edited) | Only edited_paths | Includes unchanged staged files in diff tracking for completeness |
| 6 | Read file_contents from sandbox post-copy | Read directly from source_root | Correct for retries where sandbox already has partial edits |

## Risks / Things to Revisit

- **LLM edit provider not implemented**: The current `EditProvider` protocol defines the interface; a real `LLMEditProvider` is a Phase 10/11 concern. The Orchestrator will need to construct it with an API key and model name.
- **Large file contents in provider payload**: Passing all `file_contents` to the LLM uses tokens. For large files, consider truncating at a line limit or summarising. Add a `max_file_chars` param to `CoderAgent` when needed.
- **No write ordering guarantee**: When multiple edits touch the same file, the last edit wins. The provider is responsible for producing a single coherent edit per file. Add a validation step if non-deterministic providers are used.
- **Retry semantics**: On retry, `wm.relevant_files` may need to be updated (test failures may point to a different file). The Orchestrator is responsible for updating `wm.relevant_files` before calling `CoderAgent.run` again.
- **skill_prompt not auto-loaded**: The Orchestrator must look up the skill via `SkillsRegistry` and render it before passing `skill_prompt`. If it forgets, the provider receives `None` and the coder behaves generically.
