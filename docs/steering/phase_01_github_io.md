# Phase 1 — Steering Doc: GitHub I/O Layer

**Status:** complete
**Owner:** platform / integrations
**Depends on:** Phase 0 (Settings), Phase 0.5 (Logging + Audit)
**Unblocks:** Phase 9 (PR Agent uses `GitHubClient`), Phase 10 (Orchestrator drives `IssuePoller`)

---

## Goal

Single, mockable boundary for all non-LLM GitHub work. Pollers, branch creation, commits, PR opening — all flow through one typed facade. Issue pickup mints a `trace_id` and writes the first audit event. Every later phase observes GitHub through this layer; no other module imports `pygithub` directly.

## Deliverables

| Artifact | Path | Purpose |
|---|---|---|
| Domain types | `codepilot/github_io/models.py` | `IssueRef`, `BranchRef`, `CommitRef`, `PRRef` (frozen dataclasses) |
| Filter rules | `codepilot/github_io/filters.py` | `is_assignable()` — pure selection logic |
| GitHub facade | `codepilot/github_io/client.py` | `GitHubClient` over PyGithub, base-branch selector wiring |
| Base-branch prompt | `codepilot/github_io/prompts.py` | `BaseBranchSelector` Protocol + `Fixed` / `Default` / `Interactive` impls |
| Poller | `codepilot/github_io/poller.py` | `IssuePoller` + sync/async surfaces, audit emission |
| Tests | `tests/unit/test_{gh_models,filters,gh_client,gh_client_selector,prompts,poller}.py` + `_gh_fakes.py` | 58 new tests, fully offline |

## Exit Criteria

- `GitHubClient` covers every GitHub operation later phases need: list issues, get issue, create branch, commit files, open PR.
- `IssuePoller.poll_once()` returns deterministic results when fed canned issues (verified via `FakeRepo`).
- Pickup writes `issue.picked_up` to audit log under a fresh `trace_id` per issue.
- In-progress dedupe survives across ticks.
- Branch creation and PR target both prompt the user for the base branch (via `BaseBranchSelector`); explicit `base=` argument bypasses prompt; chosen branch logged.
- `pytest` green: 153 tests passing.

---

## Files

### Source

**`codepilot/github_io/__init__.py`**
Public surface. Re-exports `GitHubClient`, `build_default_client`, `IssuePoller`, `iter_pickups`, `is_assignable`, `DEFAULT_AI_LABEL`, `IssueRef`, `BranchRef`, `CommitRef`, `PRRef`, `ComplexityFn`, plus selector types: `BaseBranchSelector`, `FixedSelector`, `DefaultBranchSelector`, `InteractiveSelector`, `resolve_base`, `OP_CREATE_BRANCH`, `OP_OPEN_PR_BASE`. Callers import only from `codepilot.github_io`; nothing imports `pygithub` outside `client.py`.

**`codepilot/github_io/models.py`**
Frozen dataclasses that carry GitHub data into the rest of the system. Decouples internal code from PyGithub mutability and version drift.
- `IssueRef` — number, title, body, labels, assignees, reporter, repo, state, created_at, url. `from_pygithub(issue, repo)` classmethod handles `None`-safe coercion (titles/bodies sometimes `None`, label/assignee lists sometimes empty).
- `BranchRef`, `CommitRef`, `PRRef` — minimal projections returned by write APIs.
Frozen prevents accidental mutation by downstream agents.

**`codepilot/github_io/filters.py`**
One pure function: `is_assignable(issue, *, in_progress_ids, ai_label, complexity_estimator, complexity_threshold) -> bool`. Rules in priority order:
1. Closed issues never assignable.
2. Currently-in-progress issues skipped.
3. Issues carrying the `ai-assignable` label always taken (even if assigned).
4. Otherwise: unassigned issues taken if either no complexity estimator is configured or its score ≤ threshold.
`ComplexityFn = Callable[[IssueRef], int]` exposed for Phase 10 to wire a real LLM-based scorer.

**`codepilot/github_io/client.py`**
PyGithub facade. Constructor takes `(gh, repo_full_name, *, base_selector=None)` — `gh` is duck-typed against the `_ClientLike` Protocol so tests inject `FakeGitHub`. `base_selector` defaults to `DefaultBranchSelector` (no prompting). Lazy `repo` property fetches the repo once and caches.
- `list_open_issues(*, labels, exclude_ids)` — passes `state="open"` + label filter to PyGithub, drops anything where `pull_request is not None`, drops excluded numbers, maps to `IssueRef`.
- `get_issue(number)` — single issue lookup.
- `list_branches()` — returns branch names; used by selector to populate candidates.
- `create_branch(name, base=None)` — when `base is None`, calls `resolve_base(self._base_selector, operation=OP_CREATE_BRANCH, candidates=list_branches(), default=repo.default_branch)` to ask the user. When `base` is explicit, no prompt. Then reads `base` SHA, calls `create_git_ref("refs/heads/{name}", sha)`.
- `commit_files(*, branch, files: dict[path, content], message)` — upsert via try-`get_contents` / update-or-create.
- `open_pr(*, title, body, head, base=None, labels, reviewers)` — when `base is None`, prompts via selector with `OP_OPEN_PR_BASE` operation label. When explicit, no prompt. Then `create_pull` + `add_to_labels` + `create_review_request` (review failure swallowed).
- `build_default_client(token, repo, *, base_selector=None)` — production wiring; defaults to `InteractiveSelector` so the CLI prompts on stdin until the TUI takes over.

**`codepilot/github_io/prompts.py`**
Base-branch prompting layer. Decouples *what* branch to use from *how* the user is asked.
- `BaseBranchSelector` Protocol — `select(*, operation, candidates, default) -> str`.
- `FixedSelector(branch)` — always returns the configured branch; validates membership when candidates non-empty. For tests + non-interactive runs.
- `DefaultBranchSelector` — returns `default` without prompting; raises if `default is None`. Cheap CI fallback.
- `InteractiveSelector(reader, writer)` — numbered list, prompt, accepts numeric index OR branch name OR empty (→ default). Re-prompts on invalid input. Different prompt label per operation: `OP_CREATE_BRANCH` → "Select BASE branch to fork from", `OP_OPEN_PR_BASE` → "Select TARGET branch to merge PR into" — same selector, different intent surfaced to user.
- `resolve_base(selector, *, operation, candidates, default)` — calls selector, validates the answer is in `candidates` (when non-empty), emits `base_branch.selected` structured log line.

**`codepilot/github_io/poller.py`**
Polling controller. One `IssuePoller` per repo per process. Constructor params: `client`, `ai_label`, `complexity_estimator`, `complexity_threshold`, `audit_log`, `clock`. Internal state: `_in_progress: set[int]`.
- `poll_once()` — sync. Calls `client.list_open_issues(exclude_ids=self._in_progress)`, applies `_filter` (delegates to `is_assignable`), and for each new issue: opens `bind_task(issue.number, repo=issue.repo)`, emits structured `issue.picked_up` log line, writes `Event.ISSUE_PICKED_UP` to audit log if wired, then `mark_in_progress(issue.number)`. Returns the new pickups so callers can spawn work.
- `mark_in_progress(n)` / `mark_done(n)` — explicit transitions; orchestrator calls these on state machine moves.
- `stream(*, interval_sec, stop)` — async generator; loops `poll_once`, yields each issue, sleeps `interval_sec` (cancellable via `stop` event). Orchestrator's polling loop is just `async for issue in poller.stream(...)`.
- `iter_pickups(poller, ticks)` — sync helper for tests/scripts; drains N ticks.

### Tests (58 new)

**`tests/unit/_gh_fakes.py`**
Tiny dataclass fakes mirroring the `pygithub` surface used by `client.py`: `FakeUser`, `FakeLabel`, `FakeIssue`, `FakeCommit`, `FakeBranch`, `FakeContent`, `FakePR`, `FakeRepo`, `FakeGitHub`. `FakeRepo` records every write call (`created_refs`, `created_files`, `updated_files`, `created_prs`) so tests assert behavior without network.

**`tests/unit/test_gh_models.py`** (3)
`IssueRef.from_pygithub` field mapping; `None`-safe coercion for `title`/`body`/`user`; frozen dataclass invariant.

**`tests/unit/test_filters.py`** (14)
Each rule in `is_assignable` has its own class: `TestStateGate`, `TestInProgress`, `TestLabel`, `TestUnassignedFlow`, `TestComplexity`. Confirms label bypasses both assignment and complexity gates; complexity threshold inclusive at boundary; parametrized over alternative label names.

**`tests/unit/test_gh_client.py`** (11)
- `TestRepoLazyLoad` — `get_repo` called once across multiple property reads.
- `TestListIssues` — open-only filter; label filter; exclusion list; PRs disguised as issues are dropped.
- `TestBranch` — `create_branch` resolves base SHA and calls `create_git_ref` with `refs/heads/...`.
- `TestCommitFiles` — creates when `get_contents` raises; updates when present; multi-file path counts.
- `TestOpenPR` — labels and reviewer applied; reviewer-request failure swallowed without aborting PR.

**`tests/unit/test_prompts.py`** (13)
- `TestFixedSelector` — returns configured branch; raises on unknown when candidates supplied; allows pass-through when candidates empty.
- `TestDefaultBranchSelector` — returns default; raises when default is `None`.
- `TestInteractiveSelector` — empty input → default; numeric index choice; branch-name choice; re-prompt on invalid then valid; different prompt label per operation; empty candidates raises.
- `TestResolveBase` — selector logged; selector returning unknown raises (defends against buggy custom selectors).

**`tests/unit/test_gh_client_selector.py`** (9)
- `TestCreateBranchSelectorPrompt` — no `base` arg invokes selector with `OP_CREATE_BRANCH` operation, `repo.default_branch` as default, and full candidate list; explicit `base=` skips selector entirely; selector's choice flows into `create_git_ref`; default selector falls back to repo default branch; raises when no default available.
- `TestOpenPRSelectorPrompt` — no `base` arg invokes selector with `OP_OPEN_PR_BASE`; explicit base skips; chosen branch reaches `create_pull`.
- `TestListBranches` — returns names from fake repo.

**`tests/unit/test_poller.py`** (8)
Shares an autouse logging-reset fixture so structured logs land in `tmp_path` per test.
- `TestPollOnceFiltering` — only assignable issues returned; in-progress filtered.
- `TestInProgressLifecycle` — pickup marks in-progress; repeat poll empty until `mark_done`.
- `TestAuditEmission` — `ISSUE_PICKED_UP` row written per issue with distinct `trace_id`s; toggling `audit_log=None` doesn't crash.
- `TestIterHelper` — `iter_pickups` drains multiple ticks, second tick empty.
- `TestStreamCancel` — async `stream()` collects pickups then exits cleanly when `stop.set()`.

---

## Architecture

```
                  ┌────────────────────────┐
                  │  IssuePoller           │
poll_once() ─────▶│  - in_progress:set[int]│
                  │  - filter via          │
                  │    is_assignable()     │
                  └─────────┬──────────────┘
                            │ list_open_issues
                            ▼
                  ┌────────────────────────┐
                  │  GitHubClient (facade) │
                  │  list / branch / commit│
                  │  / open_pr             │
                  └─────────┬──────────────┘
                            │ get_repo / get_issues / create_pull
                            ▼
                  ┌────────────────────────┐
                  │  PyGithub (Github())   │
                  └────────────────────────┘

For each new issue:
   bind_task(issue.number, repo) ─→ trace_id minted
   ├─ structlog "issue.picked_up"
   └─ audit.write(ISSUE_PICKED_UP, {issue_id, title, labels, reporter})
```

The poller is the only place where `bind_task` is called — every later agent works inside the trace pinned here.

---

## FAQ

### Q1. Why a hand-rolled facade instead of using `langchain_community.agent_toolkits.GitHubToolkit` directly?
The toolkit's purpose is to expose tools to an LLM. The polling loop is deterministic and burns no LLM tokens — running it through a tool-call layer would cost money and add a translation step for nothing. Phase 10 will wrap the same `GitHubClient` (or the toolkit) for the orchestrator agent. Two surfaces, one auth, one source of truth.

### Q2. Why frozen dataclasses (`IssueRef`, etc.) instead of using PyGithub objects directly?
PyGithub objects are mutable, do lazy network calls on attribute access, and change shape across major versions. Pinning the boundary at `IssueRef` means: tests don't need network, the rest of the codebase has stable types, and a PyGithub upgrade only ripples to `models.from_pygithub` + `client.py`.

### Q3. Why is `is_assignable` a pure function instead of a method on the poller?
Pure functions are trivially parametrizable in tests (14 cases here). The poller adds book-keeping (`in_progress`, audit emission, log binding) — that belongs to a stateful class. Mixing them into one class would force every test to construct a poller + fake repo just to assert "closed issues are skipped."

### Q4. Why is the `ai-assignable` label gate ahead of the assignment gate?
The label is an explicit human action: "I want this routed to the agent." That intent overrides everything else. If we let assignment win first, a maintainer who self-assigns then labels the issue would be silently locked out.

### Q5. Why does `complexity_estimator` default to `None`?
Phase 1 ships without an estimator — orchestrator will plug one in around Phase 10. With no estimator, the rule degrades to "take all unassigned open issues," which is the right behavior for the bring-up demo.

### Q6. Why does `commit_files` try `get_contents` first instead of always calling `update_file`?
PyGithub's `update_file` requires the existing blob SHA, which `get_contents` returns. There's no "upsert." The try/except is the cheapest way to handle "create if absent, update if present" with one entry point.

### Q7. Why is the review-request failure swallowed in `open_pr`?
GitHub blocks review requests under several non-fatal conditions: the requested reviewer left the org, lacks repo access, or is the PR author. None of those should abort PR creation — the PR is the deliverable, the reviewer is a hint. The failure is logged elsewhere (Phase 9 will hook the audit log here).

### Q8. Why does `poll_once()` return the new issues *and* mutate `in_progress`?
Two reasons: callers want the list (to spawn work) AND the dedupe must be atomic with pickup. Returning without marking opens a race where two consecutive `poll_once` calls duplicate work. Marking without returning makes the list useless. One method does both.

### Q9. Why does `bind_task` happen inside the poller, not in the orchestrator?
The trace begins at pickup. If the orchestrator pulled raw issues and bound the task itself, the audit log emission inside the poller would have no `trace_id` (and the writer would `raise ValueError`). Pinning `bind_task` here means every audit row from issue pickup forward shares the trace.

### Q10. Why a sync `poll_once` with a separate async `stream`?
Orchestrator wants `async for issue in poller.stream(...)`. Tests want fast deterministic call-and-assert. PyGithub itself is sync. Splitting them keeps async out of the unit boundary and makes the async layer trivially thin (one `asyncio.sleep` plus cancellation).

### Q11. Why a Protocol (`_ClientLike`) instead of typing against `github.Github`?
Tests inject `FakeGitHub`. A nominal type would force the fake to inherit `Github` (which has constructor side-effects and an entire HTTP stack). Protocol satisfies the type checker structurally — fakes match by shape.

### Q12. Why does `list_open_issues` skip PRs explicitly?
GitHub's REST API returns PRs in the issues endpoint with `pull_request` populated. PyGithub mirrors that. Without the skip, the orchestrator would attempt to "fix" PRs as if they were bugs.

### Q13. Why do we mint a fresh `trace_id` per issue inside the poller, not one per `poll_once` call?
A `poll_once` call may pick up multiple issues. Each issue is its own work unit and must be reconstructable independently. The trace is the issue's lifecycle, not the poller's.

### Q14. Why no retry/backoff on the `list_open_issues` call?
GitHub rate limit + transient errors are real, but the poller runs every N minutes — a missed tick is not catastrophic. Adding retries here would also retry inside `get_issues` which PyGithub already handles for some cases. Phase 13 hardening will add an outer retry decorator if monitoring shows missed ticks.

### Q15. Why does the test suite ship its own `FakeGitHub` instead of `unittest.mock.Mock`?
`Mock` returns truthy `Mock()` objects on attribute access, which silently lets bugs through ("`pr.html_url` returns a `Mock`, looks fine, breaks at runtime when stringified"). Hand-rolled fakes use real types and explicit recording — the tests fail loudly when shape drifts.

### Q16. Why a `BaseBranchSelector` Protocol instead of a hard-coded `input()` call inside `create_branch`?
Three deployment surfaces need different UX:
- CLI bring-up (Phase 0–10) — terminal prompt is correct.
- TUI (Phase 11) — prompt belongs in the approval pane, not stdin.
- CI / autonomous runs — must be non-interactive, fail closed when no default is supplied.
A Protocol lets the same `GitHubClient` serve all three by swapping the selector at construction. Hard-coding `input()` would hard-code the CLI deployment.

### Q17. Why ask separately for `create_branch` and `open_pr` when the answer is usually the same branch?
They are different decisions:
- **Create branch**: which branch are we *forking from*? Almost always the latest stable line — but not always (release-branch fixes fork from `release-1.0`, not `main`).
- **Open PR**: which branch are we *merging into*? Same intent in the common case, but for hotfixes the answer diverges (fork from `release-1.0`, merge back into `release-1.0` AND `main`).
Asking once would silently couple two independent decisions. The selector ships with one prompt label per operation so the user knows which question they're answering.

### Q18. Why bypass the selector when `base` is passed explicitly?
Explicit beats implicit. Phase 9's PR Agent and orchestrator state machine should be able to drive non-interactively when running in scripted mode (e.g. nightly runs against `develop`). Forcing a prompt every time would block automation. The rule is: pass `base=` for scripted, omit for interactive.

### Q19. Why does `resolve_base` validate that the selector's answer is in `candidates`?
A selector is user code; bugs are inevitable. Validating at the boundary turns "PR opens against a non-existent branch and GitHub returns 422" into "selector returned `'ghost'`, not among candidates" with a clear stack. The cost is one set membership check.

### Q20. Why does `IssueRef` carry both `repo` and `url` instead of computing one from the other?
The two are independent at API level: `repo` is `org/name`, `url` is the rendered issue URL (which can be a different domain on GHE). Storing both is cheap; computing one from the other costs a regex and a class of hard-to-debug edge cases.

---

## Decisions Log

| # | Decision | Alternatives | Rationale |
|---|---|---|---|
| 1 | PyGithub for non-LLM I/O | `httpx` + raw REST, GitHubToolkit | mature, typed, handles auth/pagination |
| 2 | Frozen `IssueRef` boundary | reuse PyGithub objects | testability, version-stability |
| 3 | Pure `is_assignable` separate from poller | method on poller | easy parametrization |
| 4 | Sync `poll_once` + thin async `stream` | fully async | unit-test friendliness |
| 5 | Protocol-typed `_ClientLike` for DI | nominal `github.Github` | tests don't need PyGithub HTTP stack |
| 6 | Pickup mints trace_id | orchestrator mints | trace must cover the audit emission |
| 7 | Label gate ahead of assignment gate | reverse | explicit human intent wins |
| 8 | Review-request failure swallowed | propagate | PR creation is the deliverable |
| 9 | `commit_files` upsert via try/except `get_contents` | preflight + branch | matches PyGithub's API shape |
| 10 | `BaseBranchSelector` Protocol injected at construction | hard-coded `input()` / global state | three deployment modes (CLI/TUI/CI) need three UX |
| 11 | Separate operation labels for branch vs PR base | one shared prompt | answers diverge for hotfix flows |
| 12 | Explicit `base=` arg bypasses selector | always prompt | enables scripted/non-interactive runs |

## Risks / Things to revisit

- **Rate limiting**: no backoff. Add token-bucket + secondary-rate-limit handling in Phase 13.
- **Pagination**: PyGithub's `get_issues` returns a `PaginatedList`; iteration triggers requests. Large repos may be slow on first poll. Consider capping page count.
- **Concurrent pickups**: `_in_progress` is a plain `set`. Phase 10 introduces `MAX_INFLIGHT_TASKS > 1`; if multiple coroutines call `mark_in_progress`/`mark_done`, wrap with `asyncio.Lock`.
- **PR conflict handling**: Phase 9 will detect merge conflicts and refuse auto-resolve. Today's `commit_files` would happily push on top of a conflicted branch. Add a `dry_run` parameter then.
- **`build_default_client` lazy import**: tests pass without PyGithub, but `--doctor` will not detect a missing `pygithub` install. Either add an explicit import to `doctor` or an extras_require check at startup.
