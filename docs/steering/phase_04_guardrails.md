# Phase 4 — Steering Doc: Guardrails

**Status:** complete
**Owner:** platform / safety
**Depends on:** Phase 3 (Skills — `ForbiddenAction` tripwires read here), Phase 0.5 (Logging — audit events)
**Unblocks:** Phase 7 (Coder — wraps every `execute` and `edit_file` call), Phase 9 (PR Agent — gates `git push` and `open_pr`), Phase 12 (E2E — `test_guardrail_path`)

---

## Goal

Intercept dangerous operations **before** they execute. Three layers:

1. **Shell guard** — command string → ALLOW / HITL / BLOCK decision before the sandbox executes anything.
2. **File guard** — path string → ALLOW / BLOCK decision before any read or write touches a sensitive file.
3. **HITL gate** — async approval workflow triggered either by a guard decision or a condition (large commit, PR to protected branch, max retries).
4. **Prompt guard** — regex-based injection detector applied to untrusted content (GitHub issue bodies) before they reach any LLM.

Guards are **pure**: they return a `GuardResult` with no side effects. The caller decides whether to write an audit event, surface the block in the TUI, or raise an exception. The HITL gate is the one stateful component — it blocks until the operator approves or rejects.

## Deliverables

| Artifact | Path | Purpose |
|---|---|---|
| Shared types | `codepilot/guardrails/base.py` | `Decision`, `GuardResult`, `ALLOWED` sentinel |
| Shell guard | `codepilot/guardrails/shell.py` | `ShellRule`, `ShellGuard`, 17 built-in rules |
| File guard | `codepilot/guardrails/files.py` | `FileRule`, `FileGuard`, 14 built-in patterns |
| HITL gate | `codepilot/guardrails/hitl.py` | Condition table, `ConsoleHitlGate`, `AutoApproveGate`, `AutoRejectGate`, `RaisingHitlGate`, `NeedsApproval` |
| Prompt guard | `codepilot/guardrails/prompt.py` | `PromptGuard` — 14 injection patterns |
| Public API | `codepilot/guardrails/__init__.py` | Re-exports all public symbols |
| Tests | `tests/unit/test_{shell_guard,file_guard,hitl_gate,prompt_guard}.py` | 190 tests |

## Exit Criteria

- Shell guard: 22+ malicious commands blocked or flagged HITL; 15+ benign commands pass.
- File guard: `.env`, `*.pem`, `*.key`, `.env.local`, `.env.production`, `credentials`, `id_rsa`, `.git/config`, `.netrc`, etc. all blocked; `requirements.txt`, `README.md`, `src/config.py` pass.
- HITL conditions: PR to main/master triggers, >5 file commit triggers, `git_push` triggers, `retry_count >= 2` triggers; benign operations return `None`.
- `AutoApproveGate` always returns `True`; `AutoRejectGate` always `False`; `RaisingHitlGate` raises `NeedsApproval`.
- Prompt guard: 16 injection patterns detected; 8 clean issue bodies pass.
- `pytest` green: 485 total unit tests.

---

## Files

### Source

**`codepilot/guardrails/base.py`**
Three types used by every other guardrails module.

- `Decision(str, Enum)` — `ALLOW`, `BLOCK`, `HITL`. `BLOCK` is a hard stop (no approval path); `HITL` is a soft stop (human can approve).
- `GuardResult(frozen dataclass)` — `decision`, `rule` (triggering rule name; empty string on ALLOW), `reason`. Properties: `is_allowed`, `needs_hitl`, `is_blocked`.
- `ALLOWED` — singleton `GuardResult(ALLOW, "", "")`. Guards return this constant for the clean-pass path to avoid allocating a new object per call.

**`codepilot/guardrails/shell.py`**
Shell command validator.

- `ShellRule(frozen dataclass)` — `name`, `pattern`, `decision`, `reason`, `use_regex: bool`. When `use_regex=False` the pattern is matched as a case-insensitive substring; when `True` via `re.search` with `IGNORECASE`.
- `_BUILTIN_RULES: tuple[ShellRule, ...]` — 17 rules evaluated in order (first match wins):
  - **BLOCK (4)**: `fork_bomb` (`:(){:|:`), `mkfs`, `dd_dev_wipe` (`dd if=.*of=/dev/`), `eval_subshell` (`eval\s+[\"'\`$\(]`).
  - **HITL (13)**: `git_push_force`, `git_push_force_f`, `git_push`, `git_reset_hard`, `rm_rf`, `curl_net`, `wget_net`, `pip_install_adhoc` (regex — skips `-r` and `-e` flags), `apt_get_install`, `apt_install`, `brew_install`, `npm_install_adhoc`, `chmod_world`, `sudo`.
- `ShellGuard(extra_rules=None)` — evaluates built-ins then `extra_rules`. `validate(cmd) -> GuardResult`.
- `ShellGuard.from_skill(skill)` — adds SHELL-kind `ForbiddenAction` rules from the skill as extra BLOCK rules.

**`codepilot/guardrails/files.py`**
File path validator.

- `FileRule(frozen dataclass)` — `name`, `pattern` (fnmatch glob), `decision`, `reason`, `match_full_path: bool`, `match_basename: bool`. Both default to `True` so patterns are checked against the full path string and the `os.path.basename` separately.
- `_BUILTIN_RULES: tuple[FileRule, ...]` — 14 BLOCK rules:
  - Env files: `*.env`, `.env.*`
  - TLS/PKI: `*.pem`, `*.key`, `*.pfx`, `*.p12`
  - Secrets: `*.secret`, `*credentials*`
  - SSH keys: `*id_rsa*`, `*id_ed25519*`, `*id_dsa*`, `*id_ecdsa*`
  - Credential stores: `.netrc`
  - Git auth: `.git/config` (full-path only, `match_basename=False`)
- `FileGuard(extra_rules=None)` — `validate_path(path) -> GuardResult`.
- `FileGuard.from_skill(skill)` — adds FILE-kind `ForbiddenAction` rules from the skill.

**`codepilot/guardrails/hitl.py`**
Human-in-the-loop approval gate.

- `NeedsApproval(Exception)` — `operation: str`, `context: dict`. Raised by `RaisingHitlGate` in non-interactive environments.
- `HitlCondition(ABC)` — abstract base with `name`, `description`, and `should_trigger(*, operation, context) -> bool`.
- Four concrete conditions:
  - `PrToProtectedBranch` — fires when `operation == "open_pr"` and `context["base_branch"] in protected`. Default protected set: `{"main", "master", "release", "develop"}`.
  - `LargeCommit(threshold=5)` — fires when `operation in ("create_commit", "commit")` and `files_changed > threshold`.
  - `RemotePush` — fires when `operation in ("git_push", "push")`.
  - `MaxRetriesReached(max_retries=2)` — fires when `retry_count >= max_retries`.
- `DEFAULT_CONDITIONS: tuple` — all four conditions with default parameters.
- `check_hitl_conditions(*, operation, context, conditions=None) -> HitlCondition | None` — iterates conditions, returns first that fires.
- `ConsoleHitlGate` — `needs_approval()` checks conditions; `request_approval()` prompts on stdout/stdin via `run_in_executor` (non-blocking event loop), writes `hitl.requested` + `hitl.decision` audit events if `audit` is provided.
- `AutoApproveGate` — always returns `True`. Used in tests and CI runs that should not block.
- `AutoRejectGate` — always returns `False`. Used to verify rejection-handling code paths.
- `RaisingHitlGate` — raises `NeedsApproval`. Used in fully automated pipelines where blocking is incorrect.

**`codepilot/guardrails/prompt.py`**
Prompt injection detector for untrusted text.

- `_INJECTION_PATTERNS` — 14 compiled regex patterns covering: instruction override (`"ignore previous instructions"`), role override (`"you are now"`), persona hijack (`"act as"`), fake system prompts, chat-format injection (`"\n\nHuman:"`), jailbreak keywords, template injection (`{{...}}`/`{%...%}`), LLaMA `</INST>` injection, bracket system injection.
- `PromptGuard.validate_text(text) -> GuardResult` — returns `ALLOWED` or a `BLOCK` result with the triggering rule name.
- Designed for pluggable replacement: a `NemoPromptGuard` subclass can call `nemoguardrails` when installed.

**`codepilot/guardrails/__init__.py`**
Public surface. Re-exports every symbol callers need. Importing `from codepilot.guardrails import ShellGuard, FileGuard, AutoApproveGate` covers all production use cases.

### Tests (190 new)

**`tests/unit/test_shell_guard.py`** (51)
- `test_malicious_command_blocked_or_hitl` (×22) — parametrized; every BLOCK and HITL case confirmed.
- `test_benign_command_allowed` (×15) — `ls`, `cat`, `pytest`, `git status/diff/log/add/commit`, `pip install -r/-e`, `echo`, `rg`, `python`, `find`, `grep`.
- `TestDecisionGranularity` — fork_bomb/mkfs/dd/eval → BLOCK; rm_rf/git_push/curl → HITL.
- `TestFirstMatchWins` — `git push --force` hits `git_push_force` rule not the `git_push` rule.
- `TestCaseInsensitivity` — uppercase and mixed-case commands still match.
- `TestPipRuleGranularity` — `pip install -r` and `-e` pass; bare package names are HITL.
- `TestExtraRules` — custom rule fires; built-in still fires; `from_skill` adds SHELL forbidden actions.
- `TestGuardResultHelpers` — `is_allowed/needs_hitl/is_blocked` properties on ALLOWED, BLOCK, HITL results.

**`tests/unit/test_file_guard.py`** (50)
- `test_blocked_paths` (×25) — all env variants, TLS files, secret files, credentials, SSH keys, netrc, git config.
- `test_allowed_paths` (×13) — source files, requirements, README, config.py, Dockerfile, json data, lock files.
- `TestGlobEdgeCases` — fnmatch semantics: `*.env` matches `.env` and `subdir/.env`; `.env.*` matches `.env.local`; `env.txt` is NOT blocked; `*credentials*` substring match; `.git/config` full path; `.git/COMMIT_EDITMSG` passes.
- `TestFromSkill` — skill FILE forbidden actions added to guard; custom skill rule works.
- `TestExtraRules` — extra rule appended, built-ins still work; `rule` and `reason` populated on block.

**`tests/unit/test_hitl_gate.py`** (50)
- `TestPrToProtectedBranch` — all 4 default protected branches trigger; feature/fix/chore branches pass; wrong operation passes; custom protected set; missing base_branch passes.
- `TestLargeCommit` — above threshold triggers; at/below threshold passes; `commit` operation alias; wrong operation passes.
- `TestRemotePush` — `git_push` and `push` trigger; `create_commit`, `open_pr`, `read_file`, `edit` pass.
- `TestMaxRetriesReached` — `retry_count >= 2` triggers; 0 and 1 pass; missing key passes.
- `TestCheckHitlConditionsComposite` — first match wins; nothing fires returns `None`; default conditions cover all 4 scenarios; empty conditions always `None`.
- `TestAutoApproveGate` / `TestAutoRejectGate` — always approve/reject; `needs_approval` method works.
- `TestRaisingHitlGate` — raises `NeedsApproval` with correct `operation` and `context`.
- `TestNeedsApprovalException` — `operation`, `context`, `Exception` subclass.

**`tests/unit/test_prompt_guard.py`** (39)
- `test_injection_detected` (×16) — all 14 injection patterns detected plus 2 variants.
- `test_clean_text_allowed` (×8) — real-world bug reports, feature requests, dep updates, doc issues.
- `TestPromptGuardHelpers` — rule name populated; ALLOWED sentinel returned on pass; case-insensitive; multiline clean body passes; empty string passes.

---

## Architecture

```
                      Subagent wants to execute operation
                                     │
                        ┌────────────┴──────────────┐
                        │                           │
              shell command?                  file path?
                        │                           │
                        ▼                           ▼
              ShellGuard.validate()       FileGuard.validate_path()
                        │                           │
              ┌─────────┴──────────┐     ┌──────────┴─────────┐
              │         │          │     │                     │
           ALLOW      HITL       BLOCK ALLOW                 BLOCK
              │         │          │     │                     │
           execute  ───▶│       raise    │               raise/log
                        │    GuardError  │
                        ▼               │
              HitlGate.request_approval()◄──────────────────── HITL from conditions
                        │              (large_commit, pr_to_main, git_push, max_retries)
                    ┌───┴───┐
                 approve  reject
                    │       │
                 execute  raise/log

   Untrusted text (issue body)
          │
          ▼
   PromptGuard.validate_text()
          │
   ┌──────┴──────┐
ALLOW           BLOCK
   │               │
forward to LLM   drop / log
```

---

## FAQ

### Q1. Why are guards pure (no side effects) instead of writing audit events themselves?

Guards are called in tight inner loops. A guard that writes to an audit file on every call couples fast compute to slow I/O. Separating concerns lets callers batch audit writes, mock them in tests, or skip them entirely. The HITL gate is the one exception — it owns the approval transaction and writes audit events because the before/after pair belongs to the same logical operation.

### Q2. Why is `BLOCK` a hard stop and `HITL` a soft stop?

Some operations are unconditionally dangerous (fork bomb, disk wipe, raw eval). No context justifies executing them autonomously. Others are dangerous only in some contexts (git push, rm -rf) and a human reviewing the situation might approve. `BLOCK` signals "never, full stop"; `HITL` signals "not without a human signature."

### Q3. Why does `ShellGuard` check rules in order (first match wins) instead of collecting all matches?

For command validation, the most specific rule should govern. `git push --force` matches both `git_push_force` and `git_push`. We want the decision and rule name to reflect the most specific match (`git_push_force`), not the most general. First-match with more specific rules listed earlier gives that behavior deterministically.

### Q4. Why does `pip install -r` and `pip install -e` pass but `pip install <package>` gets HITL?

Lock-file workflow: modifying `requirements.txt` and running `pip install -r requirements.txt` to sync the environment is the intended path. Arbitrary `pip install <package>` bypasses version pinning, breaks reproducibility, and could introduce supply-chain risk. The regex `pip\s+install\s+[^-]` matches package-name arguments but not flag-prefixed arguments (`-r`, `-e`, `--upgrade`).

### Q5. Why does `FileGuard` check both the full path and the basename?

A rule like `*.pem` should match `/workspace/certs/server.pem` (full path) AND `server.pem` (when the caller passes just a filename). Checking both means callers don't need to normalize paths before calling. The exception is `.git/config` — we set `match_basename=False` because a file named just `config` in any directory should not be blocked; only `.git/config` specifically is dangerous.

### Q6. Why use `fnmatch` instead of regex for file patterns?

File patterns are glob-style, not regex. `fnmatch` is the standard library tool for this. Regex would require callers to escape dots and slashes, making rules hard to read and write. `fnmatch.fnmatch` in Python treats `*` as matching everything including `/`, which is exactly what we want for path matching.

### Q7. Why four concrete `HitlCondition` subclasses instead of lambdas or a config table?

Each condition has configuration (threshold for `LargeCommit`, protected set for `PrToProtectedBranch`). Subclasses capture that config in `__init__` and expose a clean `should_trigger` method. Tests can import the class directly (`LargeCommit(threshold=3)`) without constructing the full condition table. A lambda table would make the config invisible until runtime.

### Q8. Why does `RaisingHitlGate` exist in addition to `AutoRejectGate`?

Both prevent execution, but for different reasons. `AutoRejectGate` simulates a human saying "no" — the task may recover (retry, different approach). `RaisingHitlGate` signals "this environment has no approval mechanism" — the exception propagates to the orchestrator, which logs the failure and skips the task rather than looping. CI pipelines that must not block use `RaisingHitlGate`; tests that verify rejection behavior use `AutoRejectGate`.

### Q9. Why regex injection detection instead of NeMo Guardrails for `PromptGuard`?

`nemoguardrails` is listed as a dependency but was not installed in the development environment at Phase 4 time. NeMo requires a running LLM to evaluate Colang rules, adding latency and an external dependency to the hot path. Regex patterns are instantaneous, offline, and predictable. The `PromptGuard` class is designed for replacement: a `NemoPromptGuard` subclass can wrap NeMo without changing call sites. The regex layer is a defense-in-depth first pass, not the final word.

### Q10. Why do HITL conditions check `operation` string instead of inspecting the actual command?

Conditions are evaluated by the orchestrator at the decision point (before dispatching the operation), not by the shell guard at execution time. The `operation` string is a semantic label (`"open_pr"`, `"git_push"`) that the orchestrator sets; it carries intent, not implementation. Coupling conditions to raw command strings would break whenever the command changes format.

### Q11. Why is `check_hitl_conditions` a module-level function rather than a method on the gate?

Every gate implementation has a `needs_approval` method that calls `check_hitl_conditions`. Making the condition check a standalone function allows testing it in isolation (pass any condition tuple) without constructing a gate. The function is the logic; the gate is the I/O.

### Q12. Why does `PromptGuard` not block valid Jinja/Django template files?

The template injection patterns (`{{...}}`, `{%...%}`) target issue body text, not source code. A GitHub issue body containing `{{user.exec(...)}}` is almost certainly injection; a Python file containing Jinja templates is not processed by `PromptGuard`. Callers must apply the guard only to untrusted external input, not to files they are reading from the repo.

---

## Decisions Log

| # | Decision | Alternatives | Rationale |
|---|---|---|---|
| 1 | Guards are pure (no audit writes) | Guards write audit inline | Decouples fast compute from slow I/O; easier to test |
| 2 | `BLOCK` vs `HITL` two-level decision | Single "blocked" boolean | Callers need to distinguish "never" from "needs approval" |
| 3 | First-match-wins rule evaluation | Collect all matching rules | Most specific rule governs; avoids decision ambiguity |
| 4 | `pip install [^-]` regex allows `-r`/`-e` | Block all pip install | Lock-file workflow is the intended path; not all pip use is wrong |
| 5 | fnmatch for file patterns | regex | Glob semantics match user mental model; dots are literal |
| 6 | `FileGuard` checks full path AND basename | Full path only | Callers may pass bare filenames; both checks catch the rule |
| 7 | `HitlCondition` ABC with subclasses | Lambda table, config dicts | Config injectable via `__init__`; directly importable in tests |
| 8 | `RaisingHitlGate` + `AutoRejectGate` as separate types | One "deny gate" | Different failure semantics: exception vs soft reject |
| 9 | Regex PromptGuard with NeMo plug-in interface | NeMo only, mock only | NeMo unavailable; regex is fast, offline, and predictable |
| 10 | HITL conditions check `operation` string | Parse raw commands | Semantic intent > implementation; decoupled from command format |

## Risks / Things to revisit

- **`ConsoleHitlGate` reads from stdin**: Phase 11 (TUI) replaces this with a `TextualHitlGate` that raises a modal. The swap is a constructor injection — wire `AutoApproveGate` in tests, `ConsoleHitlGate` in CLI mode, `TextualHitlGate` in TUI mode.
- **No audit write from guards themselves**: Phase 7 (Coder) must call `audit.write(Event.GUARDRAIL_BLOCK, ...)` after any non-ALLOW result. If a caller forgets, the block won't appear in the audit log. Consider a decorator helper in Phase 7.
- **NeMo Guardrails not wired**: `nemoguardrails` is in `pyproject.toml` but not installed. Phase 13 hardening should either wire it or remove the dependency.
- **Regex injection patterns may have false positives**: "Act as a reviewer" or "You are now logged in" could theoretically match. False-positive rate should be measured against a sample of real issue bodies before Phase 12.
- **`PrToProtectedBranch` protected set is hard-coded**: Repos with non-standard naming (e.g. `trunk`) need the set overridden. Phase 10 orchestrator should load the protected set from `Settings` and pass a configured `PrToProtectedBranch` to the HITL gate.
- **`ShellGuard` doesn't block `npm run` scripts that wrap dangerous commands**: A script in `package.json` named `"nuke": "rm -rf /"` would execute `npm run nuke` undetected. Phase 5 (Sandbox) addresses this via execution isolation.
