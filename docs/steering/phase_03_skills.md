# Phase 3 — Steering Doc: Skills System

**Status:** complete
**Owner:** platform / agents
**Depends on:** Phase 0 (Settings), Phase 0.5 (Logging — for registry log events)
**Unblocks:** Phase 4 (Guardrails — reads `ForbiddenAction` tripwires), Phase 7 (Coder — injects skill prompt into system message), Phase 10 (Orchestrator — selects skill per task type), Phase 13 (E2E smoke tests — `test_skills_shipped`)

---

## Goal

Give every subagent a **reusable, versioned, structured instruction set** — the Skill — that is loaded from YAML, validated at startup, and injected into the subagent's system prompt as a formatted block.

Skills carry four pieces of information:
1. **Instructions** — prose guidance for the agent.
2. **Workflow steps** — numbered recipe with success criteria per step.
3. **Forbidden actions** — tripwires the Phase 4 guardrail reads at runtime.
4. **Metadata** — version, owner, applies-to, example prompts, references.

The system is intentionally static: skills ship as YAML files in `skills/definitions/`, not as database rows or runtime-generated content. Treating them as code (version-controlled, code-reviewed) gives the same safety guarantees as the rest of the codebase.

## Deliverables

| Artifact | Path | Purpose |
|---|---|---|
| Skill data model | `codepilot/skills/base.py` | Pydantic models: `TaskType`, `AppliesTo`, `ForbiddenKind`, `ForbiddenAction`, `WorkflowStep`, `SkillExample`, `Skill` |
| YAML loader | `codepilot/skills/loader.py` | `load_skill_from_path`, `load_skill_from_mapping`, `SkillParseError` |
| Registry | `codepilot/skills/registry.py` | `SkillsRegistry` — discovery, selection, reload, programmatic registration |
| Renderer | `codepilot/skills/render.py` | `to_system_prompt` — deterministic text block for subagent injection |
| Shipped definitions | `codepilot/skills/definitions/` | `bug_fix.yaml`, `feature_addition.yaml`, `dependency_update.yaml`, `documentation.yaml` |
| Public API | `codepilot/skills/__init__.py` | Re-exports all public symbols |
| Tests | `tests/unit/test_skills_{base,loader,registry,render,shipped}.py` | 71 tests |

## Exit Criteria

- All 4 shipped skills load cleanly; `SkillsRegistry().names()` returns the full set.
- Registry selection prefers more specific skills (fewer `task_types`), breaks ties on higher version.
- Every `TaskType` shipped maps to exactly one default skill via `select(task_type=t, agent=AppliesTo.CODER)`.
- `to_system_prompt` is deterministic; renders all optional sections only when populated.
- `ForbiddenAction.matches` works for FILE (glob), REGEX, and SHELL (case-insensitive substring).
- Bad YAML drops that skill silently without breaking the rest of the registry.
- `pytest` green: 71 Phase 3 tests + all prior tests passing.

---

## Files

### Source

**`codepilot/skills/__init__.py`**
Public surface. Re-exports every symbol callers need from `codepilot.skills` — the data model types, loader functions, registry class, and renderer. Callers never import from sub-modules directly.

**`codepilot/skills/base.py`**
Core data model. All classes are frozen Pydantic models (immutable after construction).

- `TaskType` enum — `BUG_FIX`, `FEATURE_ADDITION`, `DEPENDENCY_UPDATE`, `DOCUMENTATION`, `CONFIG_CHANGE`. Each value maps 1:1 with the orchestrator's issue classifier labels.
- `AppliesTo` enum — `ORCHESTRATOR`, `EXPLORER`, `CODER`, `TESTER`, `PR_AGENT`. Identifies which subagent loads a skill.
- `ForbiddenKind` enum — `SHELL`, `FILE`, `REGEX`, `NETWORK`. Determines which matching strategy `ForbiddenAction.matches` uses.
- `ForbiddenAction` — `kind`, `pattern`, `reason`. `matches(target)` dispatches: FILE → `fnmatch.fnmatch`; REGEX → `re.search`; SHELL/NETWORK → case-insensitive substring. Phase 4 guardrails iterate `skill.forbidden_actions` before executing any shell command or file write.
- `WorkflowStep` — `id` (snake_case, pattern `^[a-z][a-z0-9_]*$`), `title`, `instructions`, optional `success_criteria`. IDs must be unique within a skill.
- `SkillExample` — `prompt`, optional `expected_workflow` (list of step ids), optional `notes`. Used for in-context examples in the rendered prompt and smoke tests in Phase 13.
- `Skill` — aggregate root. Key validators: `name` must match `^[a-z][a-z0-9_]*$`; `version ≥ 1`; `task_types` must be non-empty; `workflow_steps` must be non-empty with unique ids. Helpers: `for_task_type`, `for_agent`, `find_forbidden`.

**`codepilot/skills/loader.py`**
Pure parse + validate. No I/O beyond reading a file.

- `load_skill_from_path(path)` — reads UTF-8 YAML, rejects non-mapping top-level, delegates to `_build_skill`.
- `load_skill_from_mapping(data)` — entry point for tests and in-process definitions.
- `_build_skill` — `Skill.model_validate(data)`, wraps `ValidationError` in `SkillParseError`.
- `SkillParseError(ValueError)` — single exception type for all parse failures. Registry catches it per-file so one bad YAML never poisons the others.

**`codepilot/skills/registry.py`**
In-process registry. Thread-safe (all mutations under `threading.Lock`).

- `DEFAULT_DEFINITIONS_DIR` — resolved at import time to `skills/definitions/` relative to this file. Tests can override via `definitions_dirs`.
- `SkillsRegistry(definitions_dirs=None, eager=True)` — constructs with a list of scan directories; calls `reload()` immediately unless `eager=False`.
- `reload()` — rescans all directories, rebuilds `_by_name` dict atomically. First-seen wins on name collisions (alphabetical sort ensures determinism). Logs `skills.loaded` with names + error count; errors logged separately at ERROR level.
- `load(name)` → `Skill` or `SkillNotFound`. `get(name, default=None)` — same but returns default.
- `select(task_type, agent=None)` — filters by `for_task_type`, optionally by `for_agent`, sorts candidates by `(len(task_types), -version, name)` (ascending specificity, descending version), returns first. Raises `SkillNotFound` when empty.
- `register(skill)` — programmatic registration for tests and dynamic skills. Overwrites on name collision.
- `for_task_type(t)` → list of matching skills (unordered).
- `SkillNotFound(KeyError)` — raised by `load` and `select`.

**`codepilot/skills/render.py`**
Deterministic text renderer. Output is stable for a given Skill version — a prompt cache key can hash the output.

Sections emitted in order:
1. `═══...═══ / SKILL: name  vN / ═══...═══` header + metadata (description, task types, applies-to, owner if set)
2. `INSTRUCTIONS` — skill's `instructions` field, stripped
3. `WORKFLOW` — numbered steps with `[id=...]` tag, indented instructions, `✓ success_criteria` when set
4. `CHECKLIST` — `[ ] item` lines (omitted when empty)
5. `FORBIDDEN ACTIONS` — `- [kind] pattern  -- reason` list with a "REQUEST HUMAN APPROVAL" banner (omitted when empty)
6. `EXAMPLE PROMPTS` — bullet list with `expected steps: a → b → c` when set (omitted when empty or `include_examples=False`)
7. `REFERENCES` — URL list (omitted when empty)

### Definitions

**`codepilot/skills/definitions/bug_fix.yaml`**
Workflow: `reproduce → localize → fix → verify`. Four steps covering test-driven bug fixing. Blocks `rm -rf` (SHELL), `*.env` / `*.pem` / `.git/**` (FILE).

**`codepilot/skills/definitions/feature_addition.yaml`**
Workflow: `explore_pattern → design → implement → test → document`. Five steps for a feature branch end-to-end. Blocks same file tripwires as bug_fix plus `git push --force` (SHELL).

**`codepilot/skills/definitions/dependency_update.yaml`**
Workflow: `check_changelog → update_manifest → regenerate_lockfile → resolve_conflicts → test_all`. Blocks `pip install <package>` (SHELL, pattern `pip install`) — forces lock-file workflow instead of ad-hoc installs.

**`codepilot/skills/definitions/documentation.yaml`**
Workflow: `read_existing → draft → review_accuracy → update_index`. Blocks `*.env` FILE and the GitHub PAT REGEX `ghp_[A-Za-z0-9]{20,}` so docs writers can't accidentally commit tokens.

### Tests (71)

**`tests/unit/test_skills_base.py`** (24)
- `TestWorkflowStep` — valid construction; 5 parametrized invalid id patterns; empty title rejection.
- `TestForbiddenAction` — SHELL substring + case-insensitive; FILE glob (`*.env` matches `.env` and `config/.env`, not `env.txt`); REGEX match.
- `TestSkillSchema` — minimal valid; 4 bad names; empty task_types / empty workflow rejected; duplicate step ids rejected; immutability (Pydantic `frozen=True`); `version=0` rejected.
- `TestForTaskTypeAndAgent` — multi-type matching; agent matching.
- `TestFindForbidden` — match by kind; non-match returns `None`.

**`tests/unit/test_skills_loader.py`** (5)
- `TestLoadFromMapping` — valid dict; invalid (empty task_types) raises `SkillParseError`.
- `TestLoadFromPath` — YAML round-trip; non-mapping top-level rejected with message "must be a mapping"; invalid YAML syntax rejected.

**`tests/unit/test_skills_registry.py`** (15)
- `TestDefaultDefinitions` — 4 shipped skills load; `DEFAULT_DEFINITIONS_DIR` exists.
- `TestCustomDir` — loads only from specified dir; duplicate names → first wins, length=1.
- `TestLoadAndGet` — `load` returns `Skill`; missing raises `SkillNotFound`; `get` returns default.
- `TestSelection` — `for_task_type` filters correctly; `select` prefers narrow skill; `select` filters by agent; no match raises.
- `TestDynamicRegistration` — `register` + `load` round-trip.
- `TestReload` — picks up new files; drops deleted files.
- `TestErrorHandling` — bad YAML drops that skill, good skill still loaded.

**`tests/unit/test_skills_render.py`** (12)
- `TestRenderSections` — header (name, version, owner); instructions; workflow order (`[id=reproduce]` before `[id=fix]`); success_criteria `✓`; checklist; forbidden with "REQUEST HUMAN APPROVAL"; examples included by default; examples omitted when `include_examples=False`; references.
- `TestRenderStability` — `to_system_prompt(s) == to_system_prompt(s)`.
- `TestMinimalSkill` — CHECKLIST / FORBIDDEN ACTIONS / EXAMPLE PROMPTS / REFERENCES all absent when empty.

**`tests/unit/test_skills_shipped.py`** (15)
- `test_each_skill_loads` (×4) — name matches file, `workflow_steps` non-empty, `instructions` non-blank.
- `test_each_skill_renders_nonempty` (×4) — output contains `SKILL:`, length > 200.
- `test_each_task_type_has_a_default_skill` — all four `TaskType`s resolve via `select`.
- `test_secret_files_blocked` (×4) — every shipped skill blocks `.env` via FILE forbidden action.
- `test_dependency_update_blocks_pip_install` — `pip install requests` matches SHELL tripwire.
- `test_bug_fix_blocks_rm_rf` — `rm -rf /tmp/x` matches SHELL tripwire.
- `test_documentation_blocks_pat_pattern` — PAT string matches REGEX tripwire.

---

## Architecture

```
                   Issue arrives (Phase 1)
                          │
                          ▼
          ┌───────────────────────────────┐
          │  Orchestrator classifies task │
          │  → TaskType                   │
          └──────────────┬────────────────┘
                         │ SkillsRegistry.select(task_type, agent)
                         ▼
          ┌───────────────────────────────┐
          │  SkillsRegistry              │
          │  ┌─────────────────────────┐ │
          │  │  definitions/           │ │
          │  │  bug_fix.yaml           │ │
          │  │  feature_addition.yaml  │ │
          │  │  dependency_update.yaml │ │
          │  │  documentation.yaml     │ │
          │  └─────────────────────────┘ │
          └──────────────┬────────────────┘
                         │ Skill (frozen)
                         ▼
          ┌───────────────────────────────┐
          │  to_system_prompt(skill)      │  rendered text block
          │  ↓ injected into subagent     │
          │    system message             │
          └──────────────┬────────────────┘
                         │ skill.forbidden_actions
                         ▼
          ┌───────────────────────────────┐
          │  Phase 4 Guardrails           │  intercepts shell / file ops
          │  skill.find_forbidden(...)    │
          └───────────────────────────────┘
```

---

## FAQ

### Q1. Why YAML files instead of Python dicts or a database?
YAML is human-readable, diff-friendly, and version-controlled with the rest of the project. Skill changes go through code review — the same gate as prompt changes. A database would add a migration path and a deploy dependency for what is essentially static configuration.

### Q2. Why are `Skill` and `WorkflowStep` frozen Pydantic models?
Skills are loaded once and shared across threads. Freezing them makes sharing safe without copying. It also prevents accidental mutation during a task run (a subagent that edits its own skill by accident is a hard-to-debug category of bug).

### Q3. Why does `select` prefer narrower skills (fewer task_types)?
A skill covering only `bug_fix` is more focused than one covering `bug_fix + documentation`. When both match a task type, the narrower one provides more precise instructions. This mirrors standard protocol-resolution specificity rules: the most specific match wins.

### Q4. Why is version a tiebreaker after specificity in `select`?
Same task_type, same specificity — newer is better. An upgraded skill replaces the older one automatically without requiring registry intervention, as long as the `version` field is incremented.

### Q5. Why does the renderer use `═` / `─` box-drawing characters?
LLMs pay attention to visual structure. Box-drawing characters are less likely to appear in generated code than `===` or `---`, so section delimiters stay unambiguous when the model outputs fenced code blocks containing those characters.

### Q6. Why include `expected_workflow` in `SkillExample`?
Phase 13 smoke tests will assert that the model actually follows the workflow steps when given the example prompt. Embedding the expected sequence in the Skill definition (not the test file) makes the contract reviewable alongside the skill itself.

### Q7. Why does every shipped skill block `.env` via a FILE tripwire?
Secrets files (`.env`, `.pem`, `.git/config`) must never be written by an autonomous agent under any task type. Centralising the tripwire in each skill (rather than one global rule) means the check survives if the orchestrator injects only a subset of forbidden actions.

### Q8. Why does `dependency_update` block `pip install <package>` instead of all pip commands?
`pip install -e .` and `pip install -r requirements.txt` are legitimate operations during testing. The rule targets ad-hoc installs that bypass the lock-file workflow. Pattern `"pip install"` (substring) catches `pip install requests`, `pip install requests==2.x`, etc. while leaving lock-file-aware calls through.

### Q9. Why does the documentation skill include a REGEX tripwire for GitHub PATs?
Documentation workflows frequently involve copying example configs that accidentally include credentials. A REGEX match against `ghp_[A-Za-z0-9]{20,}` catches real PATs before they are committed or logged. SHELL and FILE tripwires wouldn't catch tokens embedded in prose.

### Q10. Why does `reload()` use first-seen-wins for duplicate names?
Directories are scanned in alphabetical order by filename within a directory, and in the order supplied to `definitions_dirs`. The rule makes the outcome deterministic and predictable — whoever is listed first owns the name — rather than silently picking the last or raising an error that aborts the entire startup.

### Q11. Why is `SkillNotFound` a `KeyError` subclass?
`KeyError` semantics are idiomatic for "key not found in a mapping." `SkillsRegistry` is conceptually a mapping from name → Skill. `except SkillNotFound` works everywhere; `except KeyError` also catches it for callers that use the generic form.

### Q12. Why does `to_system_prompt` accept `include_examples=False`?
Example prompts are useful for in-context learning but cost tokens. At inference time on a tight context budget (long file diffs, test output), an orchestrator can suppress examples and save ~200-400 tokens without losing the workflow. The flag is on the renderer, not the Skill, because the same skill may be rendered with or without examples depending on context.

### Q13. Why does `CONFIG_CHANGE` exist in `TaskType` but have no shipped skill?
The assignment's issue classifier may return `config_change` for PRs touching CI configuration. Having the enum value present avoids a `ValueError` during classification. Phase 10 (Orchestrator) will fall back to `bug_fix` skill when no skill covers the classified type, or a `config_change.yaml` will be added before Phase 13.

---

## Decisions Log

| # | Decision | Alternatives | Rationale |
|---|---|---|---|
| 1 | YAML definitions in `skills/definitions/` | Python dicts, DB | version-controlled, diff-friendly, code-reviewed |
| 2 | Frozen Pydantic for `Skill` and steps | mutable dataclass | thread-safe sharing, mutation-proof during run |
| 3 | `select` sorts by `(len(task_types), -version, name)` | first-found | deterministic specificity-then-recency ordering |
| 4 | `SkillParseError` wraps YAML + Pydantic errors | two distinct types | single catch point in registry reload loop |
| 5 | Box-drawing chars `═` / `─` as section delimiters | `===` / `---` | won't clash with model output in code fences |
| 6 | `include_examples` flag on renderer not on Skill | per-Skill flag | same skill, context-dependent token budget |
| 7 | `SkillNotFound(KeyError)` | plain `ValueError` | idiomatic for key-not-found in a mapping-like object |
| 8 | `AppliesTo` enum on Skill model | free-form string | registry `select` can filter without string comparison |
| 9 | `CONFIG_CHANGE` in `TaskType` but no YAML yet | omit until needed | avoids classification crash before Phase 10 |
| 10 | All 4 shipped skills block `.env` independently | one global rule | guard survives partial-skill injection |

## Risks / Things to revisit

- **`CONFIG_CHANGE` has no skill**: Phase 10 orchestrator needs a fallback before Phase 13 E2E tests or classification of config PRs will raise `SkillNotFound`.
- **No skill schema versioning**: future additions to `Skill` fields will be silently ignored by old YAML files (Pydantic drops unknown keys). When a new required field is added, all existing YAMLs need updating. Consider a `$schema_version` field before Phase 13.
- **`select` is greedy-first**: if two skills are equally specific and have equal versions, the alphabetical name tiebreaker is deterministic but arbitrary. Document the ordering convention in a contributing guide before adding many skills.
- **No runtime skill hot-reload**: `SkillsRegistry.reload()` exists but is not triggered automatically. Phase 10 should call it on SIGHUP (or a CLI flag) for long-running server mode.
- **`SkillExample.expected_workflow` is unchecked against actual step ids**: a typo in `expected_workflow` list is silently ignored until Phase 13 smoke tests run. Add a `model_validator` in Phase 13 to cross-check ids.
