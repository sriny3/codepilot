# Phase 10 — Steering Doc: Orchestrator (DeepAgents Refactor)

**Status:** complete — rewritten as DeepAgents `CompiledStateGraph` (2026-05-08)
**Owner:** orchestration
**Depends on:** Phase 6 (RepoExplorer — `@tool` wrappers), Phase 7 (Coder — `CODER` subagent dict), Phase 8 (TestAgent — `@tool` wrappers), Phase 9 (PRAgent — `@tool` wrappers), Phase 2 (Memory — `EpisodicStore`), Phase 4 (Guardrails — `ShellGuard`), Phase 1 (GitHub I/O — `GitHubAPIWrapper`)
**Unblocks:** Phase 11 (TUI — orchestrator runs in background thread; streams events to app)

> **NOTE — Architecture change.** The original class-based `Orchestrator` with constructor-injected agents (Phase 10 v1) has been replaced by a LangGraph `CompiledStateGraph` built with `create_deep_agent()` from the DeepAgents library. `orchestrator.py` is superseded by `deep_agent.py`. The old file remains for reference but is no longer invoked.

---

## Goal

Replace the hand-coded `Orchestrator.run_issue()` loop with a DeepAgents LLM-driven orchestrator that:

1. **Classifies** each GitHub issue into a task type (`bug_fix`, `feature_addition`, etc.) using keyword scoring.
2. **Queries** past lessons from the episodic memory store before starting work.
3. **Delegates** to subagents (RepoExplorer → Coder → TestAgent → PRAgent) via `task()` calls in the LLM's tool use.
4. **Interrupts** on risky tool calls (`open_pr`, `commit_files`) and blocks until a human approves via the HITL gate.
5. **Retries** the Coder up to `max_retries` times on test failure.
6. **Records** a lesson in episodic memory on success.

All agent logic is expressed as `@tool`-decorated functions or subagent dicts. The LLM reasons about which to call; the framework handles state, checkpointing, and interrupt/resume.

---

## Deliverables

| Artifact | Path | Purpose |
|---|---|---|
| Orchestrator builder | `codepilot/orchestrator/deep_agent.py` | `build_orchestrator(cfg)` → `CompiledStateGraph` |
| Issue classifier | `codepilot/orchestrator/classifier.py` | `classify_issue` `@tool` — keyword scoring |
| Subagent specs | `codepilot/agents/subagents.py` | `REPO_EXPLORER`, `CODER`, `TEST_AGENT`, `PR_AGENT`, `ALL_SUBAGENTS` |
| GitHub tools | `codepilot/agents/tools/github_tools.py` | `list_open_issues`, `get_issue`, `create_branch`, `commit_files`, `open_pr` — all `@tool` |
| Memory tools | `codepilot/agents/tools/memory_tools.py` | `query_lessons`, `add_lesson` — all `@tool` |
| Pipeline config | `codepilot/orchestrator/factory.py` | `PipelineConfig.from_settings(cfg)` |
| CLI wiring | `codepilot/__main__.py` | `run` command builds orchestrator + starts background thread |
| Classifier tests | `tests/unit/test_classifier.py` | 12 tests — keyword scoring, all 5 task types, default fallback |
| Subagent tests | `tests/unit/test_subagents.py` | 14 tests — spec shape, tool membership, permission lists |
| Orchestrator tests | `tests/unit/test_deep_agent.py` | 6 tests — build success, tool list, subagent count, interrupt_on, settings wiring |

---

## Exit Criteria

- `classify_issue` is a `BaseTool` (`@tool` decorated); correctly classifies 5 task types; ties broken by score; default `"bug_fix"` on no match.
- `build_orchestrator(cfg)` returns without error when settings are minimal (fake keys).
- Orchestrator has ≥ 10 tools registered including `classify_issue`, `query_lessons`, `add_lesson`, `list_open_issues`, `open_pr`.
- `ALL_SUBAGENTS` has exactly 4 entries; each has `name`, `description`, `system_prompt`, `tools`, `permissions`.
- `REPO_EXPLORER.permissions` — read-only everywhere; writes denied.
- `CODER.permissions` — write `/sandbox/**` only; writes elsewhere denied.
- `TEST_AGENT.permissions` — read+write `/sandbox/**`; writes elsewhere denied.
- `interrupt_on` contains `"open_pr"` and `"commit_files"`.
- `pytest` green: 731 passed, 3 skipped.

---

## Files

### Source

#### `codepilot/orchestrator/classifier.py`

**`classify_issue(title, body, labels) → str`** (`@tool`) — scores each of 5 categories by counting keyword matches in the combined text. Returns the category with the highest score. Ties broken by `max()` (first winner). Falls back to `"bug_fix"` on zero matches.

`_KEYWORD_RULES`: module-level list of `(keywords: list[str], category: str)` tuples evaluated in order. No LLM involved.

#### `codepilot/orchestrator/deep_agent.py`

**`_get_toolkit_tools() → list`** — builds `GitHubAPIWrapper` from settings and returns `GitHubToolkit.get_tools()`. Wraps construction in try/except; returns `[]` and logs a warning on failure (e.g. invalid credentials in tests).

**`build_orchestrator(cfg: PipelineConfig) → Any`** — main entry point. Calls `_get_toolkit_tools()`, assembles the full tool list, and calls `create_deep_agent(...)` with:
- `model = "anthropic:claude-sonnet-4-6"`
- `tools` — classifier + repo/memory/github @tools + GitHubToolkit tools
- `subagents = ALL_SUBAGENTS`
- `system_prompt = ORCHESTRATOR_PROMPT`
- `permissions` — write `/sandbox/**` allowed; write everywhere else denied; read everywhere allowed
- `interrupt_on = {"open_pr": True, "commit_files": True}`
- `store = InMemoryStore()`, `checkpointer = MemorySaver()`

`ORCHESTRATOR_PROMPT` — embedded string that instructs the LLM on the 8-step workflow: classify → query lessons → plan → repo_explorer → coder → retry loop → pr_agent → add_lesson.

#### `codepilot/agents/subagents.py`

Four subagent specification dicts consumed by `create_deep_agent(subagents=...)`:

| Dict | Permissions | Tools |
|------|-------------|-------|
| `REPO_EXPLORER` | read `/**`, write denied everywhere | `build_repo_map`, `retrieve_relevant_files`, `load_cached_repo_map`, `cache_repo_map` |
| `CODER` | write `/sandbox/**`, write denied elsewhere, read `/**` | `run_tests` + DeepAgents built-ins (`read_file`, `edit_file`, `execute`) |
| `TEST_AGENT` | read+write `/sandbox/**`, write denied elsewhere | `run_tests`, `parse_test_output` |
| `PR_AGENT` | read `/sandbox/**` only | inherits GitHub tools from orchestrator |

`CODER` also has `"skills": ["/skills/definitions/"]` — DeepAgents loads skill YAML files and injects them into the Coder's system prompt.

`ALL_SUBAGENTS = [REPO_EXPLORER, CODER, TEST_AGENT, PR_AGENT]`

#### `codepilot/agents/tools/github_tools.py`

Five `@tool` functions. Each calls `_get_wrapper()` which builds `GitHubAPIWrapper` from settings on demand (lazy, so tests can monkeypatch settings before the first call):

- **`list_open_issues(labels, exclude_ids)`** — calls `wrapper.get_issues()`, filters by label and excludes in-progress ids, returns list of `{number, title, body, labels}` dicts.
- **`get_issue(issue_number)`** — returns `{number, title, body}`.
- **`create_branch(branch_name, base_branch)`** — reads base SHA via PyGithub, creates `refs/heads/{branch_name}`, returns branch name.
- **`commit_files(branch, file_paths, message)`** — reads each file from disk, calls `wrapper.create_file()`. Returns `{"error": "merge_conflict", ...}` dict on 409/422; re-raises other exceptions.
- **`open_pr(title, body, head, base, labels, reviewers)`** — creates PR, applies labels and reviewer requests best-effort (catches exceptions from both). Returns `{pr_number, url}`.

#### `codepilot/agents/tools/memory_tools.py`

Two `@tool` functions. `_get_store()` builds `EpisodicStore()` lazily (patchable in tests):

- **`query_lessons(task_description, repo, top_k=3)`** — calls `store.task_records(SESSION_ID_DEFAULT)`, filters by repo, maps `TaskOutcome` fields to `{approach, outcome, files, issue_type}` dict, returns `[:top_k]`.
- **`add_lesson(repo, issue_type, files, approach, outcome)`** — constructs `TaskOutcome(issue_id=0, ...)`, calls `store.record_task(session_id=SESSION_ID_DEFAULT, outcome=task)`.

`SESSION_ID_DEFAULT = "default"` — module-level constant.

#### `codepilot/orchestrator/factory.py`

**`PipelineConfig`** dataclass — holds `run_config: RunConfig`, `max_retries: int`, `token_budget_repomap: int`, `tui_max_log_lines: int`. Built from `Settings` via `PipelineConfig.from_settings(cfg)`. Decouples orchestrator and agents from the settings object.

#### `codepilot/__main__.py` (`run` command)

Full wiring sequence:
1. Load and validate settings.
2. `app = CodePilotApp(max_log_lines=cfg.tui_max_log_lines)`.
3. `hitl = HITLCoordinator(app)` → `app._hitl = hitl`.
4. `orchestrator = build_orchestrator(pipeline_cfg)`.
5. Try to build `IssuePoller` from `cfg.github_token` (falls back gracefully — logs "polling disabled").
6. Start `threading.Thread(target=_bg_thread, daemon=True)` which runs `asyncio.new_event_loop().run_until_complete(_pipeline_loop())`.
7. `_pipeline_loop()` streams issues from `IssuePoller.stream()`, updates TUI via `app.post_upsert_issue()` and `app.post_append_log()`, then runs `orchestrator.stream()` per issue — piping each event chunk to the log panel.
8. `app.run()` (blocks until user quits).
9. `stop_bg.set()` to signal the background loop to stop.

### Tests

#### `tests/unit/test_classifier.py` (12 tests)

- `classify_issue` is a `BaseTool`.
- Correct classification for all 5 task types (`bug_fix`, `feature_addition`, `dependency_update`, `documentation`, `config_change`).
- Labels contribute to score.
- Multi-keyword text scores higher category wins.
- Empty text → `"bug_fix"` default.
- Invoked via `.invoke({"title": ..., "body": ..., "labels": ...})` (LangChain tool call interface).

#### `tests/unit/test_subagents.py` (14 tests)

- All 4 subagents present in `ALL_SUBAGENTS`.
- Each has required keys: `name`, `description`, `system_prompt`, `tools`, `permissions`.
- `REPO_EXPLORER.tools` contains `build_repo_map`, `retrieve_relevant_files`.
- `CODER.tools` contains `run_tests`.
- `TEST_AGENT.tools` contains `run_tests`, `parse_test_output`.
- Each subagent's `permissions` is a non-empty list.
- `REPO_EXPLORER` has write-deny permission.
- `CODER` has write-allow only for `/sandbox/**`.

#### `tests/unit/test_deep_agent.py` (6 tests)

Uses `min_env` fixture. Verifies `build_orchestrator` returns without error, registers expected tools, registers 4 subagents, sets `interrupt_on` with `open_pr` and `commit_files`.

---

## Architecture

```
codepilot run
    │
    ├─ build_orchestrator(cfg) → CompiledStateGraph
    │      │
    │      └─ create_deep_agent(
    │              model, tools, subagents, system_prompt,
    │              permissions, interrupt_on, store, checkpointer
    │         )
    │
    ├─ HITLCoordinator(app) → wired to app._hitl
    │
    ├─ IssuePoller.stream() [async, background thread]
    │      │
    │      └─ for each issue:
    │              app.post_upsert_issue(...)
    │              app.post_append_log(...)
    │              orchestrator.stream(
    │                  {"messages": [{role: user, content: issue}]},
    │                  config={"thread_id": str(issue_id)}
    │              )
    │              │
    │              ├─ LLM calls classify_issue @tool
    │              ├─ LLM calls query_lessons @tool
    │              ├─ LLM calls task("repo_explorer", ...)
    │              ├─ LLM calls task("coder", ...)
    │              │       └─ Coder calls task("test_agent", ...)
    │              │              (retry loop up to max_retries)
    │              │
    │              ├─ graph hits interrupt_on="open_pr"
    │              │       → HITLCoordinator.request_approval() blocks
    │              │       → TUI shows ApprovalPanel
    │              │       → user types [a] → hitl.resolve(approved=True)
    │              │       → graph resumes
    │              │
    │              └─ LLM calls add_lesson @tool on success
    │
    └─ app.run() [main thread — Textual event loop]
```

---

## FAQ

**Q: Why replace the class-based Orchestrator with a LangGraph graph?**
The class-based orchestrator hardcoded the pipeline sequence in Python. The LLM-driven graph can adapt: it reads the issue, consults lessons, and reasons about which subagent to call next. It also gets native HITL support (interrupt/resume) and checkpointing (crash-safe restarts) for free from LangGraph.

**Q: Why use `@tool` for classify_issue rather than having the LLM do it directly?**
Keyword scoring is deterministic, cheap, and consistent. Asking the LLM to classify every issue adds latency and variability. The `@tool` decorator exposes it to the LLM as a callable it can invoke at the right moment — the LLM requests classification, Python executes it, result flows back into the graph.

**Q: Why `_get_toolkit_tools()` returns `[]` on failure rather than raising?**
Tests use fake settings with invalid credentials. GitHub App JWT construction fails immediately. Wrapping it lets the test suite run fully offline without mocking `GitHubAPIWrapper`. In production, if toolkit tools are missing, the orchestrator falls back to the hand-written `@tool` functions in `github_tools.py`.

**Q: Why `interrupt_on = {"open_pr": True, "commit_files": True}` rather than a broader HITL?**
These are the two irreversible remote-write operations. Blocking on every shell command would make the system unusable (pytest runs dozens of subprocesses). The ShellGuard already handles dangerous local commands — HITL is reserved for operations that touch shared state outside the sandbox.

**Q: Why `threading.Thread` + `asyncio.new_event_loop()` for the background loop?**
The `IssuePoller` has an async `stream()` interface. Textual's `app.run()` owns the main thread's event loop. A daemon thread with its own asyncio loop lets both run concurrently without fighting for the event loop. `call_from_thread()` bridges them safely.

**Q: Why `memory=[]` in `create_deep_agent` rather than a memory file list?**
The AGENTS.md / memory file references in the original spec pointed to non-existent paths. Empty list is safe — the orchestrator gets its "memory" through `query_lessons` and `add_lesson` tools instead.

---

## Decisions Log

| # | Decision | Alternatives considered | Rationale |
|---|---|---|---|
| 1 | `create_deep_agent()` as orchestrator | Class-based `Orchestrator` | Native HITL interrupt/resume, checkpointing, subagent spawning; no hand-written retry loop needed |
| 2 | `@tool` functions for all agent actions | Direct Python method calls | LLM can choose which tool to call based on reasoning; tools are independently testable |
| 3 | Subagents as dicts not classes | `@dataclass SubagentSpec` | DeepAgents SDK accepts plain dicts; no extra abstraction layer |
| 4 | `_get_toolkit_tools()` silently returns `[]` | Raise on invalid credentials | Test isolation without mocking heavy dependencies |
| 5 | `SESSION_ID_DEFAULT = "default"` | Per-issue session IDs | EpisodicStore is process-scoped; a single session accumulates all lessons across tasks |
| 6 | Background `asyncio` loop in daemon thread | Integrate with Textual's event loop | Textual controls the main thread loop; independent loop avoids conflict |
| 7 | `interrupt_on` for open_pr + commit_files only | HITL on every tool call | Proportionate risk: only irreversible remote writes need human gate |

---

## Risks / Things to Revisit

- **Semantic memory not wired**: `query_lessons` queries `EpisodicStore` (in-process). The Qdrant-backed `SemanticStore` for cross-session cosine search exists but is not queried. Wire `SemanticStore.query_similar(description)` into `query_lessons` for long-running deployments.
- **WorkingMemory not used**: The `WorkingMemory` state machine exists and enforces valid transitions, but the DeepAgents orchestrator doesn't instantiate it — state tracking is implicit in the LangGraph graph state. Either remove `WorkingMemory` or use it to feed the TUI's ActiveTaskPanel.
- **max_retries not forwarded**: `PipelineConfig.max_retries` is built but not passed to `create_deep_agent()`. The retry count is baked into the `ORCHESTRATOR_PROMPT` string. Wire it as a formatted template parameter.
- **Orchestrator stream events are opaque**: The `orchestrator.stream()` loop in `_pipeline_loop()` sends raw event dicts to the log panel. Parse event structure to surface clean status messages.
- **GitHub token vs GitHub App**: `IssuePoller` uses `github_token` (PAT). The `GitHubAPIWrapper` uses App auth (`github_app_id` + `github_app_private_key`). Both can coexist but it's redundant — consolidate to one auth method.
