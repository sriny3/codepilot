# Phase 13 — Steering Doc: Hardening & Submission

**Status:** complete
**Owner:** all
**Depends on:** Phase 12 (E2E baseline must be green before hardening)
**Unblocks:** public release / submission

---

## Goal

Harden the project for external consumption and submit. Phase 13:

1. **LangSmith tracing** (bonus) — wire `LANGSMITH_API_KEY` from settings into LangChain env vars so all LLM calls are traced automatically in LangSmith when the key is present.
2. **Version bump** — `0.1.0` → `1.0.0` in `codepilot/__init__.py` and `pyproject.toml`.
3. **README** — replace scaffold placeholder with a production-grade document: architecture diagram, quick start, full feature descriptions, configuration reference table, evaluation checklist.
4. **Smoke verification** — `python tasks.py test` green on fresh checkout.
5. **Manual deliverables** (not automated): 5–7 min demo recording; LinkedIn post; `git tag v1.0.0 && git push --tags` to public repo.

---

## Deliverables

| Artifact | Path | Purpose |
|---|---|---|
| LangSmith module | `codepilot/observability/langsmith_tracing.py` | `configure_langsmith(api_key, project)` + `is_configured()` |
| Observability init update | `codepilot/observability/__init__.py` | exports `configure_langsmith`, `langsmith_active` |
| Startup wiring | `codepilot/__main__.py` | calls `configure_langsmith` in `run` command when key present; also wires `configure_logging` at startup |
| Version | `codepilot/__init__.py`, `pyproject.toml` | bumped to `1.0.0` |
| README | `README.md` | full production README |
| Unit tests | `tests/unit/test_langsmith_tracing.py` | 6 tests covering env var setting and `is_configured` |

---

## Exit Criteria

- `python tasks.py test` → 849 passed, 2 skipped (Windows symlink skip — expected).
- `python -m codepilot --version` → `codepilot 1.0.0`.
- `python -m codepilot doctor` (with valid `.env`) completes without error.
- `LANGSMITH_API_KEY=lsv2_test python -c "from codepilot.observability import langsmith_active; print(langsmith_active())"` → `False` (not activated until `configure_langsmith` called explicitly — env var alone is not enough).
- Manual: `configure_langsmith("key")` → `LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_API_KEY=key`, `LANGCHAIN_PROJECT=codepilot` all in `os.environ`.

---

## Files

### New source

#### `codepilot/observability/langsmith_tracing.py`

```
configure_langsmith(api_key, project="codepilot") → None
    Sets LANGCHAIN_TRACING_V2, LANGCHAIN_API_KEY, LANGCHAIN_PROJECT, LANGSMITH_API_KEY.
    LangChain's callback system auto-discovers these env vars on next LLM call.

is_configured() → bool
    Returns True iff LANGCHAIN_TRACING_V2 == "true" AND LANGCHAIN_API_KEY is non-empty.
```

### Modified source

#### `codepilot/observability/__init__.py`
Added import and export of `configure_langsmith`, `langsmith_active`.

#### `codepilot/__main__.py`
`run` command now:
1. Loads `get_settings()` and returns error if config invalid.
2. Calls `configure_logging(level, log_dir, fmt)` — previously logging was not initialised on `run`.
3. Calls `configure_langsmith(key, project)` if `cfg.langsmith_api_key` is set.
4. Then launches `CodePilotApp`.

#### `codepilot/__init__.py`
`__version__ = "1.0.0"`

#### `pyproject.toml`
`version = "1.0.0"`

#### `README.md`
Full rewrite. See file for content. Sections:
- Architecture diagram (ASCII)
- Quick start (5 steps)
- Feature descriptions (all 6 components + observability)
- Configuration reference table (14 env vars)
- Make targets / `tasks.py` cross-reference
- Project layout tree
- Evaluation checklist

### New tests

#### `tests/unit/test_langsmith_tracing.py` (6 tests)

| Test | Asserts |
|---|---|
| `test_configure_sets_tracing_v2` | `LANGCHAIN_TRACING_V2 == "true"` after call |
| `test_configure_sets_api_key` | `LANGCHAIN_API_KEY` and `LANGSMITH_API_KEY` equal the passed key |
| `test_configure_sets_default_project` | `LANGCHAIN_PROJECT == "codepilot"` when no `project` arg |
| `test_configure_respects_custom_project` | `LANGCHAIN_PROJECT` matches explicit `project` arg |
| `test_is_configured_false_before_setup` | `False` before any `configure_langsmith` call |
| `test_is_configured_true_after_setup` | `True` after `configure_langsmith` called |

`autouse` fixture clears the four env vars before each test via `monkeypatch.delenv`.

---

## Architecture

```
codepilot run
    │
    ├─► get_settings()                        reads .env / env vars
    │       └─► cfg.langsmith_api_key set?
    │                   │ yes
    │                   ▼
    │           configure_langsmith(key, project)
    │                   sets LANGCHAIN_TRACING_V2=true
    │                   sets LANGCHAIN_API_KEY=key
    │                   sets LANGCHAIN_PROJECT=project
    │
    └─► CodePilotApp().run()
            │
            └─► any langchain/langgraph LLM call
                    LangChain callback system auto-detects LANGCHAIN_TRACING_V2
                    sends trace to LangSmith project
```

LangSmith tracing is **passive** — once the env vars are set, every LangChain/LangGraph LLM call emits a trace automatically. No code changes needed in individual agents.

---

## FAQ

**Q: Why env vars rather than calling `langsmith.Client` directly?**
LangChain's built-in tracer reads `LANGCHAIN_TRACING_V2` and `LANGCHAIN_API_KEY` from the environment. Setting these vars at startup is the canonical approach and requires zero per-agent wiring. Calling `Client` directly would require passing it to every LLM invocation.

**Q: Why must `configure_langsmith` be called explicitly — why not auto-detect `LANGSMITH_API_KEY` in the env?**
Startup should be deliberate. `configure_langsmith` is called from `__main__.py` only after `Settings` validates the full config. Auto-detecting the env var would bypass settings validation and could activate tracing in unit tests that happen to have the key set in their environment.

**Q: Why not rotate version via `bump2version` / `hatch`?**
Single source of truth already defined: `codepilot/__init__.py` and `pyproject.toml`. A one-off bump from `0.1.0` to `1.0.0` doesn't justify adding a version-management tool.

**Q: What about the GIF and demo recording?**
Not automatable — they require running the live TUI. Steps:
1. Boot Jaeger locally (`docker run -p 16686:16686 -p 4317:4317 jaegertracing/all-in-one`).
2. Set `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317` in `.env`.
3. Record screen: `python -m codepilot run` showing poll, full task (happy path), HITL approval, guardrail block.
4. Trim to 5–7 min, upload to repo, embed in README as `![demo](docs/demo.gif)`.

**Q: Why wasn't a `test_cov` gate explicitly checked in Phase 13?**
`make test-cov` (85% gate) is validated continuously in CI. Phase 13 added 6 tests against 19 new lines — coverage cannot drop. The smoke check (`make test`) is sufficient for submission verification; `test-cov` is for CI enforcement.

---

## Decisions Log

| # | Decision | Alternatives considered | Rationale |
|---|---|---|---|
| 1 | Set LangSmith via env vars in `configure_langsmith` | Pass `langsmith.Client` to each agent | Env var approach requires zero per-agent changes; canonical LangChain method |
| 2 | Wire LangSmith + logging init in `__main__.py run` | Separate `boot.py` or lazy init | `run` command is the single startup path; no lazy init complexity needed |
| 3 | `is_configured()` checks both env vars | Check only `LANGCHAIN_TRACING_V2` | Prevents false positive when only one var is set (e.g., leftover from another tool) |
| 4 | `monkeypatch.delenv` in test fixture | `importlib.reload` to reset state | `monkeypatch` is the standard pytest approach; reload would re-import the whole module |
| 5 | Full README rewrite (not incremental patch) | Append new sections to existing README | Existing README was phase-0 placeholder; shipping a v1.0.0 with placeholder docs is wrong |
| 6 | Manual tag / push (not automated) | Script `git tag && git push` in tasks.py | Tagging public releases requires explicit user confirmation; never automate destructive/visible git ops |

---

## Risks / Things to Revisit

- **LangSmith traces LangChain calls only**: DeepAgents subagent spans and custom OTel spans are not forwarded to LangSmith. For full observability, a future phase would need to bridge OTel → LangSmith via a custom callback or the LangSmith OTel ingestion endpoint.
- **`configure_logging` called late**: Logging is now initialised in `run`, not at module import. Any log emitted during `get_settings()` (e.g., a structlog warning) uses the default un-configured logger. If early-startup logging matters, move `configure_logging` to before `get_settings()` using a bootstrap log level.
- **Demo recording is blocking**: The README references a GIF that doesn't exist yet. Until recorded and committed, the README has a dangling reference. Add `docs/demo.gif` placeholder or remove the reference until the recording is done.
- **`LANGSMITH_API_KEY` duplicated in env**: `configure_langsmith` sets both `LANGCHAIN_API_KEY` and `LANGSMITH_API_KEY`. If LangSmith's SDK changes which var it reads, only one will be correct. Monitor LangSmith release notes.
