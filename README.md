# CodePilot

**Multi-agent autonomous coding platform.** Triages GitHub issues, plans fixes, sandboxes
execution, runs tests, and opens pull requests — all from a terminal UI.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    TUI (Textual)                     │
│         [Task Table]          [Event Log]            │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
          ┌────────────────────────┐
          │   Orchestrator Agent   │  root deep agent
          │   polls GitHub issues  │  write_todos planning loop
          │   classifies tasks     │  state machine per task
          │   injects memory       │
          └────────┬───────────────┘
        ┌──────────┼──────────────────────┐
        ▼          ▼                      ▼
┌─────────────┐ ┌──────────────┐  ┌──────────────┐
│    Repo     │ │    Coder     │  │   PR Agent   │
│  Explorer   │ │    Agent     │  │              │
│             │ │              │  │ create_branch│
│ repo map    │ │ read→plan→   │  │ commit_files │
│ token budget│ │ edit→sandbox │  │ open_pr      │
│ TF-IDF +    │ │ retry loop   │  │ HITL gate    │
│ embedding   │ │ guardrails   │  └──────────────┘
└─────────────┘ └──────┬───────┘
                        │
               ┌────────▼────────┐
               │   Test Agent    │
               │ detect framework│
               │ run in sandbox  │
               │ parse report    │
               └─────────────────┘

Observability layer (all agents):
  structlog JSON → logs/codepilot-YYYY-MM-DD.jsonl
  Audit log      → logs/audit.jsonl   (PR, HITL, guardrail events)
  OpenTelemetry  → OTLP (optional, e.g. Jaeger)
  LangSmith      → LLM call tracing   (optional)
  trace_id propagated via contextvars through every agent invocation
```

---

## Quick Start

```bash
# 1 — clone and install
git clone https://github.com/<you>/codepilot-agent
cd codepilot-agent
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows

pip install -e ".[dev]"

# 2 — configure
cp .env.example .env
# edit .env — minimum required:
#   GITHUB_TOKEN=ghp_...
#   REPO_FULL_NAME=org/repo
#   OPENAI_API_KEY=sk-...   (or ANTHROPIC_API_KEY)

# 3 — verify
python -m codepilot doctor

# 4 — run tests
pytest                           # or: python tasks.py test

# 5 — launch
python -m codepilot run          # or: python tasks.py run
```

---

## Features

### Orchestrator
- Continuous GitHub issue polling (configurable interval, default 5 min)
- Label filter (`ai-assignable`) + complexity threshold
- Task classifier: `bug_fix | feature_addition | dependency_update | documentation | config_change`
- State machine: `TRIAGED → EXPLORING → IMPLEMENTING → TESTING → PR_OPENED → DONE | FAILED`
- Pre-task: inject top-3 episodic summaries + top-3 semantic lessons
- Post-success: persist lesson to semantic memory, write episodic entry
- Concurrent task limit (configurable)

### Repo Explorer
- Recursive file walker (skips `.git`, `__pycache__`, binaries)
- Per-file symbol extraction (AST) + LLM 1-line summary
- Token-budgeted repo map (default 4 000 tokens, tiktoken)
- Cached to `.codepilot/repo_map.json`; invalidated on `git diff`
- TF-IDF keyword retrieval + embedding similarity (Qdrant)

### Coder Agent
- Read → plan (`write_todos`) → edit → sandbox smoke check → spawn Test Agent
- Retry loop (max 3); HITL prompt after 2nd failure
- Unified diff preview written to `working/proposed_diff.txt`
- Guardrails on every `execute` and `edit_file` call

### Test Agent
- Detects `pytest`, `npm test`, `cargo test`
- Runs inside sandbox, normalises output to `TestReport`

### PR Agent
- Branch: `codepilot/issue-{n}-{slug}`
- Commit message template (`fix(#n): ...`)
- Structured PR body: summary, approach, files changed, test results
- Labels: `codepilot-generated`, `needs-review`; reviewer = issue reporter
- HITL gate: base = `main`/`master` or files changed > 5
- Merge conflict → `FAILED` state; no auto-resolve

### Guardrails
- Shell deny-list: `rm -rf`, `curl`, `wget`, `pip install`, paths outside `/sandbox/`
- File deny-list: `.env`, `*.pem`, `*.key`, `*credentials*`
- HITL operations: PR to main, >5 file commit, `git push`, retry > 2
- NeMo Guardrails: prompt-injection detection on issue body

### Memory
- **Working**: Pydantic `TaskState` with enforced state-machine transitions
- **Episodic**: LangGraph Memory Store, read last 3 session summaries
- **Semantic**: Qdrant `lessons` collection; cosine similarity retrieval; repo-scoped filter

### Observability
- `structlog` structured JSON logs with `trace_id`, `span_id`, `agent`, `issue_id`, `repo`
- `contextvars` propagation — subagents inherit parent `trace_id` automatically
- Audit log (append-only, fsync) for every irreversible event
- Daily log rotation (30-day retention); audit rolls at UTC midnight only
- Secret redaction middleware strips tokens/keys before write
- OpenTelemetry spans with OTLP export (optional)
- **LangSmith** LLM call tracing (set `LANGSMITH_API_KEY` to activate)
- `python -m codepilot.observability.trace <trace_id>` — reconstruct full task timeline

---

## Configuration

Copy `.env.example` to `.env` and fill in values:

| Variable | Required | Default | Description |
|---|---|---|---|
| `GITHUB_TOKEN` | yes | — | GitHub PAT with repo + PR permissions |
| `REPO_FULL_NAME` | yes | — | `org/repo` to watch |
| `OPENAI_API_KEY` | one of | — | OpenAI key for LLM + embeddings |
| `ANTHROPIC_API_KEY` | one of | — | Anthropic key (alternative) |
| `POLL_INTERVAL_MIN` | no | `5` | Minutes between issue polls |
| `MAX_RETRIES` | no | `3` | Coder retry limit before HITL |
| `TOKEN_BUDGET_REPOMAP` | no | `4000` | Max tokens for repo map |
| `QDRANT_URL` | no | `http://localhost:6333` | Qdrant instance URL |
| `QDRANT_API_KEY` | no | — | Qdrant API key (cloud) |
| `LOG_LEVEL` | no | `INFO` | `DEBUG\|INFO\|WARNING\|ERROR` |
| `LOG_DIR` | no | `./logs` | Directory for log files |
| `LOG_FORMAT` | no | `json` | `json\|console` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | no | — | OTLP endpoint (e.g. `http://localhost:4317`) |
| `LANGSMITH_API_KEY` | no | — | Activates LangSmith LLM tracing |
| `LANGSMITH_PROJECT` | no | `codepilot` | LangSmith project name |

---

## Make Targets

```
make install-dev    pip install -e .[dev]
make test           pytest
make test-cov       pytest + 85% coverage gate
make lint           ruff check
make type           mypy
make doctor         validate .env
make run            launch TUI
```

Windows (no `make`): `python tasks.py <target>`

---

## Project Layout

```
codepilot/
  orchestrator/      root agent + state machine + classifier
  agents/
    repo_explorer/   walker, summarizer, repo map, retrieval
    coder/           edit loop, diff preview
    test_agent/      runner, parser
    pr_agent/        branch, commit, PR builder
  skills/            YAML skill definitions + registry
  memory/            working, episodic, semantic
  guardrails/        shell, file, HITL, NeMo prompt guard
  observability/     structlog, OTel, audit, LangSmith, redaction
  sandbox/           local sandbox, diff generation
  github_io/         poller, client, models, filters
  tui/               Textual app
  config/            Pydantic settings
tests/{unit,integration,e2e}/
docs/steering/       per-phase design docs
```

---

## Evaluation Checklist

| Area | Implemented |
|---|---|
| Multi-agent architecture (Orchestrator + subagents) | yes |
| Context engineering (repo map, token budget, retrieval) | yes |
| Skills system (4 YAML skills, registry, prompt injection) | yes |
| Guardrails (shell, file, HITL, NeMo prompt-injection) | yes |
| Memory (working state machine, episodic, semantic Qdrant) | yes |
| TUI (Textual task table + event log, keybindings) | yes |
| PR quality (structured body, labels, reviewer, HITL gate) | yes |
| Observability (structlog, OTel, audit log, LangSmith) | yes |
| Test coverage ≥ 85% | yes (`make test-cov`) |

---

## License

MIT
