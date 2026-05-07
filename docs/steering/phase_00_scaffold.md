# Phase 0 — Steering Doc: Project Scaffold & Environment

**Status:** complete
**Owner:** platform
**Depends on:** none
**Unblocks:** Phase 0.5 (Logging), all subsequent phases

---

## Goal

Stand up a runnable Python package skeleton with deps pinned, env vars validated, test runner green, and one CLI entry point. No agent logic yet — just the chassis.

## Deliverables

| Artifact | Path | Purpose |
|---|---|---|
| Package metadata | `pyproject.toml` | deps, scripts, pytest/coverage/ruff/mypy config |
| Env template | `.env.example` | every var the app reads, with safe defaults |
| Settings loader | `codepilot/config/settings.py` | typed, validated env-driven config |
| CLI entry | `codepilot/__main__.py` | `python -m codepilot` runs |
| Sub-packages | `codepilot/{orchestrator,agents,skills,memory,guardrails,tui,sandbox,github_io,config,observability}/` | enforces module boundaries from day one |
| Build runner | `Makefile` + `tasks.py` | one-liner test/lint/run on Unix and Windows |
| Test harness | `tests/{unit,integration,e2e}/` + `conftest.py` | structure mirrors plan phases |
| Phase-0 tests | `tests/unit/test_settings.py`, `test_cli.py`, `test_layout.py` | exit criteria proof |
| Ignore | `.gitignore` | secrets, caches, logs out of git |

## Exit Criteria

- `pip install -e ".[dev]"` succeeds clean.
- `pytest --collect-only` lists ≥ 25 tests, no errors.
- `pytest tests/unit` green.
- `python -m codepilot --help` returns 0.
- `python -m codepilot doctor` returns 0 with valid `.env`, returns 1 without.
- All sub-package `__init__.py` files exist.

---

## Files

### Source

**`pyproject.toml`**
Project metadata + dep manifest. Pins runtime deps (deepagents, langchain stack, qdrant, textual, structlog, otel, langsmith, tiktoken) and dev deps (pytest, ruff, mypy, jsonschema). Configures pytest (testpaths, asyncio_mode, markers `integration`/`e2e`), coverage (85% gate), ruff (line 100, py311 target), mypy (strict). Defines `codepilot` console script → `codepilot.__main__:main`.

**`.env.example`**
Template for runtime env. Groups: GitHub (token, repo), LLM keys (OpenAI/Anthropic), polling/runtime knobs, Qdrant, observability (logging, OTel, LangSmith). Copy to `.env`, edit, never commit.

**`.gitignore`**
Excludes Python build artefacts, virtualenvs, IDE dirs, `.env`, log files, `.codepilot/` cache, `.qdrant/` data.

**`Makefile`** + **`tasks.py`**
Twin task runners. Make targets: `install`, `install-dev`, `test`, `test-unit`, `test-cov`, `lint`, `format`, `type`, `clean`, `run`, `doctor`. `tasks.py` mirrors them so Windows-without-make works (`python tasks.py test`).

**`README.md`**
One-page orientation: quick start, layout, build phases pointer, make/tasks reference.

**`codepilot/__init__.py`**
Exposes `__version__ = "0.1.0"`. Nothing else.

**`codepilot/__main__.py`**
CLI entry point. Argparse with subcommands `run` (placeholder for orchestrator+TUI in later phases) and `doctor` (validates `.env` by constructing `Settings()` and dumps resolved config with secret values masked as `***SET***`). Returns rc=0 on success, 1 on config error, 2 on unimplemented.

**`codepilot/config/__init__.py`**
Re-exports `Settings`, `get_settings` so callers do `from codepilot.config import Settings`.

**`codepilot/config/settings.py`**
Single Pydantic `BaseSettings` class loaded from env (and optionally `.env` file). All env vars typed. `SecretStr` for credentials (auto-masks in repr). Bounded ints for runtime knobs (`poll_interval_min ∈ [1,120]`, etc). `repo_full_name` regex-validated. `model_validator` enforces "at least one LLM key set." `lru_cache`'d `get_settings()` accessor — reads env once per process; tests `cache_clear()`.

**`codepilot/{orchestrator,agents/...,skills,memory,guardrails,tui,sandbox,github_io,observability}/__init__.py`**
Empty placeholders. Their job at this phase is structural: lock module boundaries before any code lands. Subsequent phases populate them.

### Tests

**`tests/conftest.py`**
Two fixtures shared across the suite:
- `clean_env` — `monkeypatch.delenv` for every CodePilot env var so tests start from a known empty state.
- `min_env` — depends on `clean_env`, then sets the minimum vars needed for `Settings()` to validate (`GITHUB_TOKEN`, `REPO_FULL_NAME`, `OPENAI_API_KEY`).

**`tests/unit/test_settings.py`**
20 tests across six classes: required-field presence, repo regex, LLM-key requirement (neither/either), defaults, bound enforcement (parametrized), log_level/log_format enums, secret masking in repr, `lru_cache` identity.

**`tests/unit/test_cli.py`**
5 tests: empty argv prints help and exits 0; `--version` returns 0; `--help` returns 0; `doctor` with valid env returns 0; `doctor` with missing env returns 1.

**`tests/unit/test_layout.py`**
Smoke. Asserts every expected sub-package `__init__.py` exists, `pyproject.toml` exists, `Makefile` or `tasks.py` exists. Catches accidental package deletions.

---

## FAQ

### Q1. Why a package skeleton before any agent code?
Module boundaries are cheap to draw on day one and very expensive to redraw later. We will spawn subagents that import from `agents/`, guardrails that import from `guardrails/`, memory tiers that import from `memory/`. If those packages don't exist yet, every later phase silently grows circular imports as code lands "wherever it fits." The empty `__init__.py` files are a contract.

### Q2. Why `pydantic-settings` instead of plain `os.getenv`?
Three reasons stacked:
1. **Fail fast.** A typo in `POLL_INTERVAL_MIN=fivve` should kill the process at boot, not at minute 23 of a polling loop.
2. **Type discipline.** `SecretStr` keeps tokens out of repr/log output by default — a hard requirement before Phase 0.5 redaction lands.
3. **One source of truth.** Tests, CLI, and orchestrator all `get_settings()`. No scattered `os.getenv` calls means no drift.

### Q3. Why bound everything (`ge=1, le=120`) instead of trusting the caller?
The orchestrator is a long-running loop with autonomous network actions (PRs, branches, commits). A `MAX_RETRIES=999` typo turns into a billing accident. Bounds are a guardrail against operator error, not the agent.

### Q4. Why both `Makefile` and `tasks.py`?
Primary dev box is Windows (per environment). `make` isn't standard there. `tasks.py` is the cross-platform fallback. Same task names in both — no diverging muscle memory.

### Q5. Why pin OTel / structlog / langsmith deps in Phase 0 even though logging is Phase 0.5?
Dep resolution is global. Pinning them once with everything else avoids a second resolver run that could downgrade existing pins. Cost: a few MB of unused bytes. Benefit: reproducible install.

### Q6. Why split tests into `unit/integration/e2e` from the start?
CI gates differ. Unit runs on every commit. Integration runs on PR. E2E runs on demand (real GitHub, real money). Folder = gate. If we wait until Phase 12 to split, every "fast" test is slow and every gate is stale.

### Q7. Why require **at least one** of `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` instead of forcing one specific provider?
The assignment lets the LLM be GPT-4o or Claude. Hard-coding a single provider in `Settings` would force a code change to swap. The `model_validator` enforces "at least one is set" without picking sides.

### Q8. Why `lru_cache` on `get_settings()`?
`Settings()` re-parses env on every construction. A polling loop that calls it 10× per minute pays a needless tax. Cache once at process start, clear in tests where env changes.

### Q9. Why `extra="ignore"` in `SettingsConfigDict`?
The dev `.env` will accumulate scratch vars. Strict mode would reject the whole file on a single unknown key — bad UX. The trade-off: a typo on a known field (e.g. `LOG_LEVL=DEBUG`) silently uses default. Mitigation: `doctor` subcommand will be extended in Phase 0.5 to dump the resolved config so typos are visible on demand.

### Q10. Why `PyGithub` AND `langchain-community`'s `GitHubToolkit`?
Toolkit is the LLM-callable surface (Phase 1). Direct PyGithub is for non-agent code paths: poller (deterministic loop, no LLM cost), audit log enrichment (look up reporter login from issue ID). Mixing is fine — they share auth via `GITHUB_TOKEN`.

### Q11. Why coverage gate `85` and not `100`?
TUI and integration glue resist meaningful unit tests. 85 forces real coverage on `orchestrator/`, `guardrails/`, `agents/`, `memory/` — the parts where bugs cause data loss or runaway cost. Pushing to 100 would reward fake tests for boilerplate.

### Q12. Why a `doctor` subcommand?
First debugging question on any new install: "is my env right?" Without `doctor`, the answer requires running the orchestrator, hitting an obscure failure, and decoding it. `doctor` is the pre-flight check.

### Q13. Why ship `.env.example` instead of documenting vars in README?
Code drifts from prose. `.env.example` is read by `cp .env.example .env`. If a var is missing in the example, onboarding fails immediately. README docs go stale silently.

### Q14. Why no logger configured yet — print() in `__main__.py`?
Phase 0.5 owns logging end-to-end (structlog + JSON + trace_id). A throwaway `logging.basicConfig` here would either be ripped out or contaminate the real config. Keeping `__main__.py` to `print()` for now is honest scaffolding.

### Q15. Why `case_sensitive=False` on env vars?
Windows env vars are conventionally upper-snake. Bash users sometimes lowercase. Pydantic's default is case-sensitive matching of the field name (lowercase), which would silently miss `GITHUB_TOKEN` and load nothing. Toggling off avoids the gotcha.

---

## Decisions Log (Phase 0)

| # | Decision | Alternatives weighed | Rationale |
|---|---|---|---|
| 1 | `pydantic-settings` for config | `os.getenv` + manual checks; `dynaconf` | Native Pydantic, type-safe, Secret support, stdlib-friendly |
| 2 | `qdrant-client` over `chromadb` | chromadb | per user steer; better ops story, server mode |
| 3 | `tasks.py` mirror of Makefile | PowerShell-only script | stays POSIX-friendly for CI Linux runners |
| 4 | Coverage threshold 85 | 70 / 100 | matches plan §Test Strategy |
| 5 | Sub-package skeletons created empty | create on demand | locks module boundaries |
| 6 | `lru_cache` on `get_settings` | reload per call | startup-stable config; explicit cache_clear in tests |

## Risks / Things to revisit

- **`extra="ignore"`** masks env typos. Phase 0.5 must add a `config_dump` to `doctor`.
- **Single `.env` file.** Multi-repo orchestration may need `.env.<repo>` later. Defer.
- **No lockfile yet.** `pyproject.toml` has caret ranges. Add `uv.lock` or `pip-compile` output before the v1.0 tag.
