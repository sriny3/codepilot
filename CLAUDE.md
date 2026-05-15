# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Windows (no make): `python tasks.py <task>`
Unix: `make <task>`

| Task | Command |
|---|---|
| Install (runtime) | `pip install -e .` |
| Install (with dev deps) | `pip install -e ".[dev]"` |
| Run all tests | `python tasks.py test` |
| Run unit tests only | `python tasks.py test-unit` |
| Run with coverage (85% gate) | `python tasks.py test-cov` |
| Lint | `python tasks.py lint` |
| Format | `python tasks.py format` |
| Type check | `python tasks.py type` |
| Run app | `python tasks.py run` |
| Validate env | `python tasks.py doctor` |

Run a single test file: `python -m pytest tests/unit/test_shell_guard.py`
Run a single test: `python -m pytest tests/unit/test_shell_guard.py::TestShellGuard::test_block_rm_rf`

Integration tests are skipped by default (`@pytest.mark.integration`). Enable: `pytest -m integration`.
E2E tests require `E2E=1` env var and a live GitHub repo.

## Environment Setup

Copy `.env.example` → `.env`. Required vars:

- `GITHUB_TOKEN` (PAT) **or** `GITHUB_APP_ID` + `GITHUB_APP_PRIVATE_KEY` (GitHub App auth)
- `REPO_FULL_NAME` (e.g. `org/repo`)
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GROQ_API_KEY` (at least one required)

Workspace: repo is auto-cloned to `.codepilot/workspace/{repo_name}/` at task start and deleted after the task completes (DONE or FAILED). No manual clone needed.

Optional but commonly needed: `QDRANT_URL`, `LANGSMITH_API_KEY`, `LOG_FORMAT=console` (dev).

Note: pydantic-settings reads `.env` into the `Settings` object only — it does NOT export to `os.environ`. The `run` command explicitly exports all API keys to `os.environ` after settings load so LangChain/deepagents can pick them up.

Run `python -m codepilot doctor` to validate env before starting.

Settings are loaded once via `get_settings()` (lru_cached). In tests, call `get_settings.cache_clear()` after monkeypatching env.

## Architecture

CodePilot is a multi-agent system with a Textual TUI. The root Orchestrator agent spawns subagents (RepoExplorer → Coder → TestAgent → PRAgent) per GitHub issue. The module layout mirrors this agent hierarchy.

### Module Boundaries

```
codepilot/
  config/          Settings (pydantic-settings, validated at boot)
  observability/   Structured logging, OTel tracing, audit log, redaction
  github_io/       GitHub client, issue poller, prompts, models
  memory/          Working memory (task state machine), episodic, semantic (Qdrant)
  skills/          Skill definitions (YAML), registry, render to system prompt
  guardrails/      Shell + file + prompt guards; HITL gate
  sandbox/         Local execution sandbox, diff generation
  agents/
    repo_explorer/ RepoMap builder (token-budget-aware AST walk)
    coder/         Edit application
    test_agent/    Test runner (pytest/npm/cargo detect) + output parser
    pr_agent/      Branch naming, commit message, PR body builder
    tools/         LangChain tool wrappers (GitHub, repo, test ops)
  orchestrator/    Issue classifier, state machine, agent factory
  tui/             Textual app (4-panel layout)
```

### Data Flow per Task

1. `IssuePoller` yields an issue → `bind_task(issue_id)` mints a `trace_id` in contextvars
2. Orchestrator classifies (`TaskType`: bug_fix / feature_addition / dependency_update / documentation / config_change), selects matching `Skill`, transitions `WorkingMemory` state machine: `TRIAGED → EXPLORING → IMPLEMENTING → TESTING → PR_OPENED → DONE|FAILED`
3. RepoExplorer builds `RepoMap` (≤4000 tokens by default; Python symbols via AST), scores files by keyword or Qdrant embedding similarity
4. Coder agent reads files on-demand (paths only in prompt), edits in sandbox, spawns TestAgent, retries up to `MAX_RETRIES` (HITL after 2 failures)
5. PRAgent creates branch `codepilot/issue-{n}-{slug}`, commits, opens PR with labels `codepilot-generated` + `needs-review`
6. `WorkingMemory.for_subagent()` snapshots state for handoff — file paths, not contents

### Observability

Every component must use the context system. Call `bind_task(issue_id)` at issue pickup and `bind_span(name)` per agent invocation. The `trace_id` flows through all logs, the audit log, PR body footer (`Trace-Id:`), and commit message trailer.

- Structured logs: `get_logger(__name__)` from `codepilot.observability.logger` → JSON (prod) / console (dev)
- Audit log: `AuditLog.write(event, details)` — append-only JSONL, fsync per write, schema-validated against `AUDIT_ENVELOPE_SCHEMA` + `DETAIL_SCHEMAS`; requires an active `trace_id` in context
- Redaction: all log/audit writes pass through `redact()` which strips token/key/auth patterns

### Guardrails

Shell guard (`ShellGuard`) evaluates commands before execution. Rules: `BLOCK` (no approval path) vs `HITL` (requires human approval in TUI). Skills can inject additional `ForbiddenAction` entries via `ShellGuard.from_skill(skill)`. File guard blocks writes to `.env`, `*.pem`, `*.key`, `*credentials*`, etc.

HITL gates also trigger for: PR to main/master, commit touching >5 files, any `git push`, retry count ≥ 2.

### Skills System

Skills live in `codepilot/skills/definitions/*.yaml`. Each defines `name`, `task_types`, `applies_to`, `instructions`, `workflow_steps` (id + title + instructions), `forbidden_actions`, and `example_prompts`. Load via `SkillsRegistry.load(name)`. Render to a system prompt string via `codepilot.skills.render`. The Orchestrator selects skill by `TaskType` and passes it to subagent at spawn.

### Memory Tiers

- **Working** (`memory/state.py`): `WorkingMemory` Pydantic model + `WorkingMemoryRegistry`. State transitions enforced — invalid edges raise `InvalidTransition`. Cleared on terminal state (`DONE`/`FAILED`). Never pass contents to subagents; use `for_subagent()` which returns paths only.
- **Episodic** (`memory/episodic.py`): LangGraph Memory Store. Session summaries written at end, last 3 read at Orchestrator startup.
- **Semantic** (`memory/semantic.py`): Qdrant collection `lessons`. Lesson added after merged PR; top-3 retrieved by cosine similarity before each new task.

### Test Fixtures

`tests/conftest.py` provides:
- `clean_env` — wipes all CodePilot env vars
- `min_env` — sets minimum valid vars on top of `clean_env`

Use `min_env` for any test that constructs `Settings()`. Use `QdrantClient(":memory:")` for semantic memory tests (no server needed).

## Implementation Status (Phases)

Phases 0–0.5 (scaffold + observability): complete
Phase 1 (GitHub I/O): complete
Phase 2 (Memory tiers): complete
Phase 3 (Skills): complete
Phase 4 (Guardrails): complete
Phase 5 (Sandbox): complete
Phase 6 (Repo Explorer): complete (map + scorer)
Phase 7 (Coder): partial (edits layer done)
Phase 8 (Test Agent): complete (runner + parser)
Phase 9 (PR Agent): complete (builder)
Phase 10 (Orchestrator): partial (factory started)
Phase 11 (TUI): complete (4-panel dashboard, streaming logs, HITL gate, [i] modal)
Phases 12–13 (E2E + hardening): not started

See `docs/steering/` for per-phase design notes and decisions.
