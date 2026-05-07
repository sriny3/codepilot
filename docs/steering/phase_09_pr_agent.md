# Phase 9 — Steering Doc: PR Agent

**Status:** complete
**Owner:** agents / github
**Depends on:** Phase 1 (GitHub I/O — `GitHubClient.create_branch`, `commit_files`, `open_pr`), Phase 2 (Memory — `WorkingMemory`, `TestRunSummary`), Phase 5 (Sandbox — `LocalSandbox.read_file`), Phase 8 (Test Agent — populates `wm.test_results` and `wm.proposed_diff`)
**Unblocks:** Phase 10 (Orchestrator — checks `wm.state == PR_OPENED` after calling `PRAgent.run`)

---

## Goal

Open a GitHub pull request from a tested sandbox diff and record the outcome in `WorkingMemory`. The PR Agent:

1. **Creates** a branch named `{prefix}/issue-{id}` via `GitHubClient.create_branch`.
2. **Reads** changed files from the sandbox (identified by `+++ b/<path>` lines in `wm.proposed_diff`).
3. **Commits** those files to the new branch via `GitHubClient.commit_files`.
4. **Opens** a pull request with a generated title and body via `GitHubClient.open_pr`.
5. **Records** `PR #<n>: <url>` in `wm.notes` and transitions state `TESTING → PR_OPENED`.

All metadata helpers live in `builder.py` — pure functions that are independently testable without any GitHub or sandbox dependency.

## Deliverables

| Artifact | Path | Purpose |
|---|---|---|
| Builder utilities | `codepilot/agents/pr_agent/builder.py` | `make_branch_name`, `make_commit_message`, `build_pr_title`, `build_pr_body`, `format_test_summary`, `extract_changed_files` |
| Agent | `codepilot/agents/pr_agent/agent.py` | `PRAgent` |
| Public API | `codepilot/agents/pr_agent/__init__.py` | Re-exports all public symbols |
| Builder tests | `tests/unit/test_pr_builder.py` | 30 tests — branch name, commit msg, PR title/body, diff extraction |
| Agent tests | `tests/unit/test_pr_agent.py` | 18 tests — state transitions, branch/commit/PR creation, labels, reviewers |

## Exit Criteria

- `make_branch_name` returns `"{prefix}/issue-{id}"`.
- `extract_changed_files` parses `+++ b/<path>` headers from unified diff text.
- `build_pr_body` embeds test summary and truncated diff; omits diff section when `proposed_diff=None`.
- `PRAgent.run` transitions `TESTING → PR_OPENED`; raises `InvalidTransition` from IMPLEMENTING or TRIAGED.
- Branch created with issue ID in name; files from diff committed; PR opened with title containing issue ID.
- Missing sandbox files silently skipped (file deleted, not in sandbox).
- `wm.notes` contains `PR #<n>: <url>` after `run`.
- `pytest` green: 748 passed, 2 skipped.

## Files

### Source

#### `codepilot/agents/pr_agent/builder.py`

Pure utility functions. No I/O, no imports from sandbox or GitHub.

**`make_branch_name(issue_id, *, prefix="codepilot") → str`** — returns `f"{prefix}/issue-{issue_id}"`.

**`make_commit_message(issue_id, issue_title) → str`** — `f"codepilot: fix #{issue_id} — {issue_title}"`.

**`build_pr_title(issue_id, issue_title) → str`** — `f"fix: #{issue_id} {issue_title}"`.

**`format_test_summary(test_results: TestRunSummary | None) → str`** — human-readable markdown. `None` → `"No test results."`. Shows `N passed`, `N failed`, and a **Failures:** list when `failures` is non-empty.

**`build_pr_body(*, issue_id, issue_title, proposed_diff, test_summary, max_diff_chars=3000) → str`** — Markdown body: `Fixes #N: <title>` header, `## Test Results` section, optional `## Diff` fenced block. Long diffs truncated with `... (truncated)` suffix.

**`extract_changed_files(diff_text) → list[str]`** — uses `_DIFF_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)` to extract sandbox-relative paths from unified diff headers.

#### `codepilot/agents/pr_agent/agent.py`

**`PRAgent`**:
- `__init__(gh_client, sandbox, *, branch_prefix="codepilot", base_branch=None)` — `base_branch=None` delegates base resolution to `GitHubClient` (uses `DefaultBranchSelector`).
- `run(wm, issue_title, *, pr_labels=(), reviewers=()) → WorkingMemory`:
  1. `wm.transition(TaskState.PR_OPENED)`.
  2. `make_branch_name` → `gh_client.create_branch(name, base=self._base_branch)`.
  3. Emit `Event.BRANCH_CREATED`.
  4. `extract_changed_files(wm.proposed_diff or "")` → read each from sandbox (skip missing).
  5. `make_commit_message` → `gh_client.commit_files(branch, files, message)`.
  6. Emit `Event.COMMIT_CREATED`.
  7. `build_pr_title` + `build_pr_body` → `gh_client.open_pr(title, body, head, base, labels, reviewers)`.
  8. Emit `Event.PR_OPENED`.
  9. `wm.notes.append(f"PR #{pr_ref.number}: {pr_ref.url}")`.
  10. Return `wm`.

#### `codepilot/agents/pr_agent/__init__.py`

Re-exports: `PRAgent`, `build_pr_body`, `build_pr_title`, `extract_changed_files`, `format_test_summary`, `make_branch_name`, `make_commit_message`.

### Tests

#### `tests/unit/test_pr_builder.py` (30 tests)

Six classes:

- `TestMakeBranchName` (4) — default prefix, custom prefix, issue ID present, prefix present.
- `TestMakeCommitMessage` (3) — issue ID present, title present, returns string.
- `TestBuildPrTitle` (3) — issue ID present, title present, returns string.
- `TestFormatTestSummary` (7) — None input, passed count, failed count, no failures section on all-pass, failures section present, zero passed shows "0 passed", returns string.
- `TestBuildPrBody` (7) — issue ID, title, test summary embedded, diff section present, diff section absent when None, truncation, no truncation on short diff.
- `TestExtractChangedFiles` (6) — single file, multiple files, empty diff, no `+++` lines, nested path, returns list.

#### `tests/unit/test_pr_agent.py` (18 tests)

One class `TestPRAgent`:

- Transitions to PR_OPENED; returns same wm; branch created; branch name contains issue ID; branch name uses prefix; files committed; PR opened; PR title contains issue ID; PR title contains issue title; URL recorded in notes; URL contains domain; labels forwarded; reviewers forwarded; `InvalidTransition` from IMPLEMENTING; `InvalidTransition` from TRIAGED; no diff still opens PR; missing sandbox file skipped silently; test results embedded (state check).

## Architecture

```
PRAgent.run(wm, issue_title)
    │
    ├─► wm.transition(PR_OPENED)
    │
    ├─► make_branch_name(wm.issue_id, prefix=…)
    │       └─► gh_client.create_branch(name, base=…)
    │               → BranchRef(name, base_sha, repo)
    │
    ├─► extract_changed_files(wm.proposed_diff)
    │       └─► _DIFF_FILE_RE: "+++ b/<path>" → list[str]
    │
    ├─► sandbox.read_file(rel) for each changed path
    │       (FileNotFoundError → skip silently)
    │
    ├─► make_commit_message(wm.issue_id, issue_title)
    │       └─► gh_client.commit_files(branch, files, message)
    │               → CommitRef(sha, files_changed, branch, repo)
    │
    ├─► build_pr_title / build_pr_body / format_test_summary
    │       └─► gh_client.open_pr(title, body, head, base, labels, reviewers)
    │               → PRRef(number, url, base, head, title, labels, reviewer)
    │
    ├─► wm.notes.append("PR #<n>: <url>")
    │
    └─► log BRANCH_CREATED, COMMIT_CREATED, PR_OPENED
```

## FAQ

**Q: Why are builder functions in a separate `builder.py` rather than inline in `agent.py`?**
Pure functions are unit-testable without any fixture setup. `test_pr_builder.py` (30 tests) covers every formatting edge case — truncation, None inputs, zero counts — without needing a `FakeRepo` or `LocalSandbox`. The agent tests focus on orchestration: did the right calls happen in the right order?

**Q: Why parse `+++ b/<path>` from the diff rather than using `wm.relevant_files`?**
`wm.relevant_files` lists files the Coder was given to read, not necessarily the files it actually changed. The diff is the authoritative record of what changed. A file in `relevant_files` but unchanged in the diff should not create a new commit entry. Similarly, the Coder may write a file not in `relevant_files` (e.g., a new file), and that would appear in the diff.

**Q: Why silently skip missing sandbox files?**
The Coder may delete a file (produces a `--- a/f` / `+++ /dev/null` entry). Those don't have a `+++ b/<path>` line, so `extract_changed_files` never returns them. For any other edge case where a file appears in the diff header but is absent from the sandbox, a `FileNotFoundError` is swallowed. Raising would abort the PR entirely over a file that may have been intentionally removed. The commit will just have fewer files — better than no PR at all.

**Q: Why is `base_branch=None` the default?**
`GitHubClient` already has a `BaseBranchSelector` abstraction that resolves the base via `DefaultBranchSelector` (reads `repo.default_branch`). Passing `None` delegates to that logic, so the PR Agent doesn't need to know the repo's default branch name. The Orchestrator can override it for repos with a non-standard default.

**Q: Why emit `BRANCH_CREATED`, `COMMIT_CREATED`, `PR_OPENED` separately rather than one `PR_COMPLETE` event?**
`AUDIT_EVENTS` in `events.py` marks all three as audit-required. They have different detail schemas (branch name + SHA, commit SHA + file count, PR number + URL). Splitting them lets the audit log answer "when was the branch created?" vs "when was the PR opened?" — useful for latency debugging.

## Decisions Log

| # | Decision | Alternatives considered | Rationale |
|---|---|---|---|
| 1 | Parse `+++ b/<path>` from diff | Use `wm.relevant_files` | Diff is authoritative; relevant_files may include unchanged files or omit new files |
| 2 | Skip missing sandbox files | Raise `FileNotFoundError` | Deleted files have no `+++ b/` line; other missing files shouldn't abort the PR |
| 3 | Builder functions in separate module | Inline in agent.py | Pure functions testable without fixtures; 30 tests with no setup overhead |
| 4 | `base_branch=None` delegates to selector | Require explicit base | `GitHubClient` already has `DefaultBranchSelector`; avoids duplication |
| 5 | Three separate audit events | One `PR_COMPLETE` event | Each event has a distinct schema and audit value; granularity aids debugging |

## Risks / Things to Revisit

- **Large diffs**: `max_diff_chars=3000` may truncate meaningful context. Phase 10 should drive this from `settings.py`.
- **Binary files**: `sandbox.read_file` returns a string. Binary files (images, compiled artifacts) would produce encoding errors if they appear in `wm.relevant_files`. The Coder should not produce diffs for binary files; add a content-type check if needed.
- **Branch already exists**: `GitHubClient.create_branch` raises if the branch already exists (via `create_git_ref`). Retry scenarios (Orchestrator calls PRAgent twice) would fail. Add a `force=True` or check-then-delete-if-exists option in Phase 10.
- **Commit message encoding**: `make_commit_message` uses an em dash (`—`). GitHub accepts UTF-8 commit messages, but some CI systems may not. Switch to `—` or `: fix` if issues arise.
- **No PR body stored in WM**: `wm.notes` records only the PR number and URL. The full PR body is not stored. If the Orchestrator needs to retry with a revised body, it must regenerate it. Add `wm.pr_body: str | None` in Phase 10.
