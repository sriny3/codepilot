# DeepAgents Full Refactor — Design Spec

**Date:** 2026-05-06
**Status:** approved
**Scope:** Complete replacement of Python-class agent architecture with `create_deep_agent()` LLM-driven agents.

---

## Problem

The existing codebase implements agents as Python classes with `run()` methods. The assignment requires:
- Orchestrator instantiated via `create_deep_agent()` from `deepagents`
- Subagents spawned via the `task` tool
- `FilesystemPermission` for sandbox confinement
- `GitHubToolkit` from `langchain_community` for GitHub operations
- HITL via `interrupt_on`

None of these are wired. The entire orchestration layer must be replaced.

---

## Prerequisite — GitHub App Setup

`GitHubAPIWrapper` requires GitHub App authentication (not PAT). One-time manual setup:

1. github.com → Settings → Developer settings → GitHub Apps → New GitHub App
   - Name: `codepilot-dev`
   - Homepage URL: `https://github.com` (placeholder)
   - Webhook: uncheck Active
   - Permissions: Issues R/W, Pull requests R/W, Contents R/W, Metadata R
2. Create app → note **App ID**
3. Generate private key → download `.pem`
4. Install App on target repo
5. Add to `.env`:
   ```
   GITHUB_APP_ID=<number>
   GITHUB_APP_PRIVATE_KEY=<path/to/key.pem or raw PEM contents>
   GITHUB_REPOSITORY=org/repo
   ```
   Remove `GITHUB_TOKEN`.

`settings.py` gains: `github_app_id: str`, `github_app_private_key: str`.
`GITHUB_TOKEN` becomes optional (kept for backwards compat with tests).

---

## Architecture

```
IssuePoller (background thread)
    ↓ yields IssueRef
DeepAgentsOrchestrator.handle_issue(issue_ref)
    ↓
CompiledStateGraph  ←  create_deep_agent(...)
    │
    ├── tools: GitHubToolkit + classify_issue + repo_tools + memory_tools
    ├── subagents: [repo_explorer, coder, test_agent, pr_agent]
    ├── permissions: /sandbox/** write-allow, /** write-deny, /** read-allow
    ├── interrupt_on: open_pr=True, commit_files=True
    ├── store: InMemoryStore       ← episodic memory
    └── checkpointer: MemorySaver  ← enables interrupt + resume

TUI (Textual, 4 panels)
    ├── IssuesPanel    ← poll feed
    ├── ActiveTaskPanel ← current state/todos/skill
    ├── LogsPanel      ← streaming agent events
    └── ApprovalPanel  ← HITL gate (approve/reject/inspect)

Custom @tool layer (deterministic Python)
    ├── github_tools.py   ← wraps GitHubAPIWrapper
    ├── repo_tools.py     ← wraps RepoMap + scorer + Qdrant embedding
    ├── test_tools.py     ← wraps runner + parser
    └── memory_tools.py   ← wraps Qdrant semantic store

Domain modules (kept, called by tools)
    ├── agents/repo_explorer/map.py, scorer.py
    ├── agents/coder/edits.py (diff gen)
    ├── agents/test_agent/runner.py, parser.py
    └── agents/pr_agent/builder.py
```

---

## Tool Layer

### `codepilot/agents/tools/github_tools.py`

Wraps `GitHubAPIWrapper` instantiated from settings. All functions decorated `@tool`.

| Tool | Args | Returns |
|---|---|---|
| `list_open_issues` | `labels: list[str], exclude_ids: list[int]` | `list[dict]` |
| `get_issue` | `issue_number: int` | `dict` |
| `create_branch` | `branch_name: str, base_branch: str` | `str` |
| `commit_files` | `branch: str, file_paths: list[str], message: str` | `str` |
| `open_pr` | `title, body, head, base, labels, reviewers` | `dict` |

`commit_files` catches `GithubException` with "merge conflict" message → returns `{"error": "merge_conflict", ...}` so orchestrator can set task to FAILED without auto-resolving.

`GitHubToolkit.from_github_api_wrapper(wrapper).get_tools()` passed directly to orchestrator for full LangChain toolkit (20+ tools).

### `codepilot/agents/tools/repo_tools.py`

| Tool | Args | Returns | Notes |
|---|---|---|---|
| `build_repo_map` | `root_path: str, max_tokens: int = 4000` | `str` | calls `RepoMap.build()` |
| `retrieve_relevant_files` | `issue_body: str, repo_root: str, top_k: int = 10` | `list[str]` | TF-IDF first pass → Qdrant embedding re-rank |
| `cache_repo_map` | `root_path: str, map_text: str` | `None` | writes `.codepilot/repo_map.json` + SHA |
| `load_cached_repo_map` | `root_path: str` | `str \| None` | returns None if SHA changed since cache |

Cache invalidation: store `{"sha": git_head_sha, "map": text}`. On load, compare current `git rev-parse HEAD` to stored SHA; if changed, return None.

### `codepilot/agents/tools/test_tools.py`

| Tool | Args | Returns |
|---|---|---|
| `run_tests` | `sandbox_path: str, command: str, timeout: float` | `dict` (passed, failed, failures) |
| `parse_test_output` | `raw_output: str, framework: str` | `dict` |

### `codepilot/agents/tools/memory_tools.py`

| Tool | Args | Returns |
|---|---|---|
| `query_lessons` | `task_description: str, repo: str, top_k: int = 3` | `list[dict]` |
| `add_lesson` | `repo: str, issue_type: str, files: list[str], approach: str, outcome: str` | `None` |

### `codepilot/orchestrator/classifier.py`

`classify_issue(title, body, labels) → str`

Keyword rules first (fast, deterministic):
- "fix", "bug", "error", "crash", "fail" → `bug_fix`
- "add", "feature", "implement", "support" → `feature_addition`
- "bump", "upgrade", "update", "dependency", "version" → `dependency_update`
- "doc", "readme", "comment", "typo" → `documentation`
- "config", "env", "setting", "yaml", "toml" → `config_change`

LLM fallback (structured output) when no keyword matches with confidence ≥ 0.6.

---

## Subagent Specs

All defined in `codepilot/agents/subagents.py` as `SubAgent` TypedDicts.

### `REPO_EXPLORER`

```python
{
    "name": "repo_explorer",
    "description": "Maps a repository and retrieves files relevant to an issue.",
    "system_prompt": REPO_EXPLORER_PROMPT,
    "tools": [build_repo_map, retrieve_relevant_files,
              load_cached_repo_map, cache_repo_map],
    "permissions": [
        FilesystemPermission(operations=["read"], paths=["/**"], mode="allow"),
        FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
    ],
}
```

System prompt instructs: call `load_cached_repo_map` first; if None, call `build_repo_map` then `cache_repo_map`; call `retrieve_relevant_files`; return structured result with `repo_map_path` and `relevant_files`.

### `CODER`

```python
{
    "name": "coder",
    "description": "Implements code changes in the sandbox given relevant files and a skill.",
    "system_prompt": CODER_PROMPT,
    "skills": ["/skills/definitions/"],
    "tools": [run_tests],
    "permissions": [
        FilesystemPermission(operations=["write"], paths=["/sandbox/**"], mode="allow"),
        FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
        FilesystemPermission(operations=["read"], paths=["/**"], mode="allow"),
    ],
}
```

System prompt instructs: read relevant files, `write_todos` to plan, `edit_file` to implement (surgical edits preferred), `execute` smoke check, delegate to `test_agent`, retry up to 3× on failure.

### `TEST_AGENT`

```python
{
    "name": "test_agent",
    "description": "Runs the test suite in the sandbox and reports structured results.",
    "system_prompt": TEST_AGENT_PROMPT,
    "tools": [run_tests, parse_test_output],
    "permissions": [
        FilesystemPermission(operations=["read", "write"], paths=["/sandbox/**"], mode="allow"),
        FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
    ],
}
```

### `PR_AGENT`

```python
{
    "name": "pr_agent",
    "description": "Creates a branch, commits sandbox changes, and opens a structured PR.",
    "system_prompt": PR_AGENT_PROMPT,
    "tools": [*github_toolkit_tools, build_pr_body],
}
```

System prompt instructs: branch name `codepilot/issue-{n}-{slug}` (slugify title, kebab-case); commit message `fix(#{n}): {summary}` with bullet body; PR body must include issue summary, approach, files changed, test results, `Closes #{n}`; labels `codepilot-generated`, `needs-review`; reviewer = issue reporter login; if merge conflict encountered return FAILED signal without resolving.

---

## Orchestrator

`codepilot/orchestrator/deep_agent.py` — replaces `orchestrator.py`.

```python
def build_orchestrator(cfg: PipelineConfig) -> CompiledStateGraph:
    github_wrapper = GitHubAPIWrapper()
    toolkit_tools = GitHubToolkit.from_github_api_wrapper(github_wrapper).get_tools()

    return create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        tools=[
            *toolkit_tools,
            classify_issue,
            build_repo_map,
            retrieve_relevant_files,
            load_cached_repo_map,
            cache_repo_map,
            query_lessons,
            add_lesson,
        ],
        subagents=[REPO_EXPLORER, CODER, TEST_AGENT, PR_AGENT],
        system_prompt=ORCHESTRATOR_PROMPT,
        permissions=[
            FilesystemPermission(operations=["write"], paths=["/sandbox/**"], mode="allow"),
            FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
            FilesystemPermission(operations=["read"], paths=["/**"], mode="allow"),
        ],
        interrupt_on={
            "open_pr": True,
            "commit_files": True,
        },
        store=InMemoryStore(),
        checkpointer=MemorySaver(),
        memory=["/memory/AGENTS.md"],
    )
```

`ORCHESTRATOR_PROMPT` instructs:
1. `classify_issue` → determines skill to inject into coder
2. `query_lessons` → inject top-3 past lessons into coder context
3. `write_todos` → break issue into checklist
4. `task("repo_explorer", ...)` → explore repo
5. `task("coder", ..., skill=<classified_skill>)` → implement
6. `task("test_agent", ...)` → verify (via coder delegation)
7. `task("pr_agent", ...)` → open PR
8. `add_lesson` on success

State machine (`TRIAGED → EXPLORING → IMPLEMENTING → TESTING → PR_OPENED → DONE | FAILED`) encoded as ordered todo items + system prompt instruction sequence. Not a Python state machine — LLM follows the sequence.

### HITL Flow

```
orchestrator.stream({"messages": [issue_prompt]}, config={"thread_id": str(issue_id)})
    ↓ streams events → TUI LogsPanel
    ↓ hits interrupt_on (open_pr or commit_files)
    → GraphInterrupt raised → HITLCoordinator.request_approval(op, details)
    → TUI ApprovalPanel renders pending op
    → user presses [a] → orchestrator.invoke(None, config)  # resumes
    → user presses [r] → orchestrator.invoke(Command(resume=False), config)
```

---

## TUI — 4 Panels

`codepilot/tui/app.py` — full rewrite.
`codepilot/tui/widgets.py` — new, contains IssuesPanel, ActiveTaskPanel, ApprovalPanel.
`codepilot/tui/hitl.py` — new, HITLCoordinator.

### Layout

```
┌─────────────────────┬──────────────────────────────┐
│   IssuesPanel       │   ActiveTaskPanel             │
│   DataTable         │   Static: title/state/skill   │
│   # | title | state │   ListView: todos             │
├─────────────────────┼──────────────────────────────┤
│   LogsPanel         │   ApprovalPanel               │
│   Log widget        │   Static: op description      │
│   streaming events  │   Input: approve/reject       │
└─────────────────────┴──────────────────────────────┘
  [i] New task  [s] Skip  [q] Quit  [l] Toggle logs
```

### Widgets

**`IssuesPanel`** — `DataTable`, columns `#, title, state`. Updated via `call_from_thread` as poller yields issues.

**`ActiveTaskPanel`** — `Static` labels (issue, state, skill, retry, trace_id) + `ListView` for todos. Updated on each LangGraph event containing `write_todos` output.

**`LogsPanel`** — `Log` widget with `max_lines` limit. Receives every streamed agent event.

**`ApprovalPanel`** — hidden by default. Shown when `HITLCoordinator.request_approval()` is called. Displays operation description. `Input` widget accepts `a`/`approve`, `r`/`reject`, `i`/`inspect`. On submit: resolves coordinator future, hides panel.

### `HITLCoordinator` (`codepilot/tui/hitl.py`)

```python
class HITLCoordinator:
    def __init__(self, app: CodePilotApp) -> None: ...

    def request_approval(self, operation: str, details: dict) -> bool:
        """Called from orchestrator thread. Blocks until TUI resolves."""
        # Posts to TUI via call_from_thread.
        # Uses threading.Event to block caller.
        # Returns True (approved) or False (rejected).
```

### Keybindings

| Key | Action |
|---|---|
| `i` | Open Input prompt → free-form task → orchestrator.invoke without GitHub issue |
| `s` | Skip current issue → add to poller exclude list |
| `q` | Quit app |
| `l` | Toggle LogsPanel visibility |

---

## Remaining Gap Fixes (included in this refactor)

### NeMo Guardrails
`codepilot/guardrails/prompt.py` — add `NemoPromptGuard` subclass:
```python
class NemoPromptGuard(PromptGuard):
    """Uses NeMo Guardrails when available; falls back to regex."""
    def validate_text(self, text: str) -> GuardResult: ...
```
Feature-flagged: `if importlib.util.find_spec("nemoguardrails"): use NemoPromptGuard`.

### PR Branch Slug
`agents/pr_agent/builder.py`:
```python
def make_branch_name(issue_id: int, title: str, *, prefix: str = "codepilot") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40]
    return f"{prefix}/issue-{issue_id}-{slug}"
```

### PR Body — Approach Section
`build_pr_body` gains `approach: str` parameter. New section:
```markdown
## Approach
{approach}
```

### Merge Conflict Detection
`commit_files` tool catches `GithubException` containing "merge conflict" or HTTP 409 → returns `{"error": "merge_conflict", "message": ...}`. Orchestrator system prompt instructs: on merge conflict response, do not retry, report FAILED to TUI.

### Repo Explorer Embedding Retrieval
`retrieve_relevant_files` tool: TF-IDF scorer first pass (top-20), then embed query + top-20 summaries via `text-embedding-3-small`, Qdrant `repo_chunks` collection cosine re-rank → return top-K. Collection created on first `build_repo_map` call; invalidated with cache.

### /sandbox/ Path Validation in Shell Guard
`codepilot/guardrails/shell.py` — add pattern:
```python
(re.compile(r"(?<!/sandbox)/[a-z]"), "path_outside_sandbox")
```
Blocks commands targeting absolute paths outside `/sandbox/`.

---

## File Changes Summary

### New files
```
codepilot/agents/tools/__init__.py
codepilot/agents/tools/github_tools.py
codepilot/agents/tools/repo_tools.py
codepilot/agents/tools/test_tools.py
codepilot/agents/tools/memory_tools.py
codepilot/agents/subagents.py
codepilot/orchestrator/deep_agent.py
codepilot/orchestrator/classifier.py
codepilot/tui/widgets.py
codepilot/tui/hitl.py
tests/agents/__init__.py
tests/agents/test_tool_github.py
tests/agents/test_tool_repo.py
tests/agents/test_tool_test.py
tests/agents/test_tool_memory.py
tests/agents/test_classifier.py
tests/agents/test_subagent_specs.py
tests/agents/test_orchestrator.py
tests/tui/test_panels.py
tests/tui/test_hitl_coordinator.py
tests/tui/test_keybindings.py
```

### Modified files
```
codepilot/config/settings.py          ← add github_app_id, github_app_private_key
codepilot/__main__.py                 ← wire build_orchestrator in run command
codepilot/tui/app.py                  ← full rewrite, 4 panels
codepilot/tui/models.py               ← extend TaskRow for new panel data
codepilot/agents/pr_agent/builder.py  ← slug + approach + merge conflict
codepilot/guardrails/shell.py         ← /sandbox/ path validation
codepilot/guardrails/prompt.py        ← NeMo subclass
codepilot/observability/__init__.py   ← exports for new modules
.env.example                          ← add GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY
```

### Deleted files
```
codepilot/orchestrator/orchestrator.py
codepilot/agents/repo_explorer/agent.py
codepilot/agents/coder/agent.py
codepilot/agents/test_agent/agent.py
codepilot/agents/pr_agent/agent.py
tests/unit/test_coder_loop.py
tests/unit/test_retry_logic.py
tests/unit/test_coder_guardrail_block.py
tests/unit/test_diff_preview.py
tests/unit/test_tui_layout.py
tests/unit/test_tui_keybinds.py
tests/unit/test_tui_approval.py
tests/unit/test_tui_streaming.py
tests/unit/test_tui_models.py
tests/e2e/test_pipeline.py
tests/e2e/test_tui_pipeline.py
```

---

## Testing Strategy

**Keep** — all domain utility tests survive unchanged:
observability, github_io, memory, skills, guardrails, sandbox, repo_explorer utilities, test_agent utilities, pr_agent builder, langsmith_tracing, settings.

**Delete** — tests for Python agent classes being removed (listed above).

**New `tests/agents/`** — uses `FakeChatModel` (no API key):
- Tool shape tests (mocked APIWrapper/Qdrant)
- Classifier accuracy ≥ 90% on labelled fixtures
- SubAgent spec validity (required keys, permission shapes)
- `build_orchestrator` returns `CompiledStateGraph`; `.invoke()` with `FakeChatModel` completes

**New `tests/tui/`** — uses Textual `Pilot` driver:
- All 4 panels mount
- HITL coordinator approve/reject flow
- Keybinding actions

---

## System Prompt Content (key instructions per agent)

Each prompt is a module-level string constant in its respective file. Minimum required instructions:

**`ORCHESTRATOR_PROMPT`**: You are an autonomous coding agent. For each GitHub issue: (1) call `classify_issue` to determine task type, (2) call `query_lessons` for top-3 past lessons and include them in context, (3) call `write_todos` to plan the implementation, (4) call `task("repo_explorer", ...)` to map the repo, (5) call `task("coder", ...)` injecting the classified skill name and relevant files, (6) on test failure retry coder up to 3×, (7) call `task("pr_agent", ...)` when tests pass, (8) call `add_lesson` on success. On merge conflict response, do NOT retry — report FAILED.

**`REPO_EXPLORER_PROMPT`**: You map a repository for a coding task. Call `load_cached_repo_map` first; if None, call `build_repo_map` then `cache_repo_map`. Call `retrieve_relevant_files` with the issue description. Return structured output: `{"repo_map_path": "...", "relevant_files": [...]}`.

**`CODER_PROMPT`**: You implement code changes in the sandbox. Read relevant files with `read_file`. Call `write_todos` to plan before editing. Use `edit_file` for surgical edits (prefer over full-file rewrites). Run `execute` as a smoke check. If tests are needed call `task("test_agent", ...)`. On test failure, revise and retry. Max 3 retries; on 3rd failure surface to human via the HITL interrupt.

**`TEST_AGENT_PROMPT`**: You run and report test results. Call `run_tests` then `parse_test_output`. Return structured `{"passed": N, "failed": N, "failures": [...]}`.

**`PR_AGENT_PROMPT`**: You open a pull request. Branch name MUST be `codepilot/issue-{n}-{slug}` (slugify title to kebab-case, max 40 chars). Commit message format: `fix(#{n}): {one-line summary}` + bullet body + `Closes #{n}`. PR body MUST include sections: issue summary, approach, files changed, test results, `Closes #{n}`. Labels: `codepilot-generated`, `needs-review`. Reviewer: issue reporter login. On merge conflict: return `{"status": "FAILED", "reason": "merge_conflict"}` — do NOT attempt to resolve.

---

## Known Simplifications vs Assignment

| Requirement | Assignment | This design | Reason |
|---|---|---|---|
| HITL on commit | Only when >5 files changed | Always interrupt on `commit_files` | `interrupt_on` is static — no conditional support in API |
| HITL on git push | Block `git push` via guardrail | Shell guard blocks it; no `interrupt_on` needed | Shell guard already covers this |
| State machine | Formal Python transitions | LLM follows ordered todos in system prompt | DeepAgents architecture; LLM is the state machine |
| Subagent tool inheritance | Explicit per assignment | pr_agent inherits GitHub tools from orchestrator via DeepAgents default | Explicit `tools=` override only needed for permissions-restricted agents |

---

## Qdrant `repo_chunks` Population

`build_repo_map` tool, after building the map, also chunks file contents (max 512 tokens/chunk), embeds via `text-embedding-3-small`, and upserts into Qdrant collection `repo_chunks` (payload: `{path, repo}`). `retrieve_relevant_files` then: TF-IDF scorer (top-20) → embed query → Qdrant cosine search filtered by `repo` → return top-K re-ranked results. Collection invalidated (deleted + recreated) when cache SHA changes.

---

## Constraints

- `create_deep_agent` default model `anthropic:claude-sonnet-4-6` — requires `ANTHROPIC_API_KEY` in production.
- `interrupt_on` requires `checkpointer` — `MemorySaver` used (in-memory, non-persistent).
- `GitHubAPIWrapper` requires GitHub App (not PAT) — setup documented above.
- NeMo subclass feature-flagged — `nemoguardrails` import optional.
- Existing 849 tests: ~200 deleted (agent class tests), ~649 remain green, ~60 new added.
- System prompts are the primary control surface — prompt quality directly affects agent reliability. Each prompt must be tested via `FakeChatModel` to verify tool call ordering.
