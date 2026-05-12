# CodePilot: How It All Works

A plain-language guide for anyone who wants to understand what this system does and how every piece connects.

---

## 1. The One-Sentence Summary

CodePilot watches a GitHub repository for issues, assigns each one to a team of AI agents, writes the code fix inside a safe sandbox, and opens a pull request — pausing only when it needs a human to approve a risky step.

---

## 2. The Analogy That Makes Everything Clearer

Imagine a small software shop with five roles:

| Role | Does what | CodePilot equivalent |
|------|-----------|----------------------|
| Manager | Reads incoming tickets, assigns work | **Orchestrator** |
| Librarian | Figures out which files are relevant | **RepoExplorer** |
| Developer | Writes and edits code | **Coder** |
| QA Engineer | Runs the tests, reports results | **TestAgent** |
| Submitter | Opens the pull request | **PRAgent** |

The Manager (Orchestrator) never closes a ticket they are unsure about without asking you first. That "pause and ask" mechanism is called **HITL** (Human-in-the-Loop).

---

## 3. System Architecture — The Big Picture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Your Terminal (TUI)                           │
│                                                                         │
│  ┌─────────────┐  ┌──────────────┐                                     │
│  │ Issues      │  │ Active Task  │  ← row 1: short, side by side       │
│  │ (live feed) │  │ (state+hbeat)│                                     │
│  ├─────────────┴──┴──────────────┤                                     │
│  │       Activity Log            │  ← row 2: full-width, tallest       │
│  │   (timestamped, color-coded)  │                                     │
│  ├───────────────────────────────┤                                     │
│  │  Approval (hidden until HITL) │  ← row 3: auto-height, green       │
│  └───────────────────────────────┘                                     │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │  [a]pprove / [r]eject
                               │
┌──────────────────────────────▼──────────────────────────────────────────┐
│                     HITL Coordinator (threading.Event)                  │
│          Blocks the AI thread until you type [a] or [r]                 │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────────┐
│                    Orchestrator  (LangGraph graph)                      │
│                                                                         │
│   IssuePoller → classify_issue → query_lessons → build_repo_map         │
│       → task("repo_explorer") → task("coder") → task("pr_agent")       │
│                    ↑ retry loop (max 3) ↑                               │
└────────┬──────────────────────┬──────────────────────┬──────────────────┘
         │                      │                      │
  ┌──────▼──────┐        ┌──────▼──────┐       ┌──────▼──────┐
  │ RepoExplorer│        │   Coder     │       │  PRAgent    │
  │  (read-only)│        │ (sandbox    │       │ (opens PR)  │
  │             │        │  write only)│       │             │
  └─────────────┘        └──────┬──────┘       └─────────────┘
                                │
                         ┌──────▼──────┐
                         │  TestAgent  │
                         │ (runs pytest│
                         │  / npm etc) │
                         └─────────────┘
         │
┌────────▼──────────────────────────────────────────────────────────────┐
│                         Safety Layer                                   │
│                                                                        │
│  ShellGuard: blocks fork-bombs/mkfs, requires approval for rm-rf etc  │
│  FileGuard:  blocks writes to .env *.pem *.key *credentials*          │
│  LocalSandbox: all code runs in a temp directory; path traversal =err │
└───────────────────────────────────────────────────────────────────────┘
         │
┌────────▼──────────────────────────────────────────────────────────────┐
│                         Memory Layer                                   │
│                                                                        │
│  Working Memory  — per-task state machine (TRIAGED → DONE/FAILED)     │
│  Episodic Store  — records outcomes after each completed task          │
│  Semantic Store  — Qdrant vector search of past lessons                │
└───────────────────────────────────────────────────────────────────────┘
```

---

## 4. Step-by-Step Workflow

This is the complete journey of a single GitHub issue from open to merged PR.

### Step 1 — IssuePoller Notices a New Ticket

```
GitHub API
    │
    │  list_open_issues() every N minutes
    ▼
IssuePoller.poll_once()
    │
    ├─ filter: must have the "codepilot" label
    ├─ filter: not already in-progress
    └─ filter: complexity score ≤ threshold
    │
    ▼
IssueRef { number, title, body, labels, reporter }
    │
    ▼
TUI: "issue.picked_up issue_id=42 title='Fix login bug'"   ← appears in log panel
TUI: Issues panel row added with state=TRIAGED
```

**In plain English:** The poller is like a mail sorter who checks the inbox every few minutes, picks up only letters labelled "for AI", and hands them to the manager.

---

### Step 2 — Orchestrator Classifies the Issue

```python
classify_issue(
    title="Fix login crash on empty password",
    body="NullPointerException in auth.py line 42",
    labels=["bug", "codepilot"]
)
# Returns: "bug_fix"
```

The classifier scores keywords:
- "fix", "crash", "exception" → **bug_fix** wins with 3 points
- No "add", "feature" → feature_addition gets 0

The result tells the Orchestrator which **Skill** to load. A Skill is a YAML file with specific instructions — "when fixing bugs, always write a failing test first."

---

### Step 3 — Check Past Lessons

```python
query_lessons(repo="org/myrepo", issue_type="bug_fix", top_k=3)
# Returns: [
#   {"approach": "check null before .get()", "outcome": "success"},
#   ...
# ]
```

Before starting work the Orchestrator asks: "Have we solved something like this before?" The top 3 past lessons are injected into the coder's context. This is how the system gets smarter over time.

---

### Step 4 — RepoExplorer Maps the Codebase

The Orchestrator spawns the **RepoExplorer** subagent:

```
RepoExplorer receives:
  - issue description
  - permission: read /** (entire repo), write: DENIED

RepoExplorer calls:
  1. load_cached_repo_map()   ← check .codepilot/repo_map.json
     - cache hit? return it (cheap)
     - cache miss? → build_repo_map() → cache_repo_map()
  
  2. retrieve_relevant_files(
       description="Fix login crash on empty password",
       repo_map=<map>
     )
     → ["src/auth.py", "tests/test_auth.py"]

Returns to Orchestrator:
  {"repo_map_path": ".codepilot/repo_map.json",
   "relevant_files": ["src/auth.py", "tests/test_auth.py"]}
```

**In plain English:** The Librarian speed-reads the entire codebase, caches the index, then highlights the relevant chapters.

**Cache trick:** The repo map is cached with a Git SHA key. If no commits happened since last run, the expensive AST walk is skipped entirely.

---

### Step 5 — Coder Writes the Fix

The Orchestrator spawns the **Coder** subagent with:
- The relevant file list from RepoExplorer
- The classified skill instructions
- Past lessons as additional context

```
Coder permission envelope:
  write: /sandbox/**   ← ONLY inside sandbox
  write: /**           ← DENIED (can't touch real files yet)
  read:  /**           ← can read anything for context

Coder workflow:
  1. read_file("src/auth.py")
  2. write_todos([
       "1. Write failing test for empty password",
       "2. Add null-check in auth.validate()",
       "3. Run tests"
     ])
  3. edit_file("tests/test_auth.py", ...)  ← write failing test
  4. execute("pytest tests/test_auth.py")  ← smoke check
  5. edit_file("src/auth.py", ...)         ← fix the bug
  6. execute("pytest tests/test_auth.py")  ← verify fix
  7. task("test_agent", ...)               ← full test suite
```

Every `execute()` call passes through **ShellGuard** first. If the command matches a dangerous pattern it either hard-blocks (no way forward) or asks you for approval.

---

### Step 6 — TestAgent Runs the Suite

```
TestAgent receives:
  - sandbox path
  - test command (e.g. "pytest")
  - timeout (default 120 seconds)

TestAgent calls:
  1. run_tests(sandbox_path, "pytest", timeout=120)
     → raw output string

  2. parse_test_output(raw_output)
     → {"passed": 12, "failed": 0, "failures": []}

Returns to Coder:
  {"passed": 12, "failed": 0, "failures": []}
```

If tests fail, the Coder retries. After 3 failures it surfaces a HITL interrupt — the system cannot fix this without human guidance.

---

### Step 7 — HITL Gate (Human Approval)

Some actions always require your approval before proceeding:

| Trigger | Why it pauses |
|---------|--------------|
| `open_pr` tool called | Permanent action on GitHub, can't undo easily |
| `commit_files` tool called | Writes to remote repository |
| `git push --force` command | Rewrites remote history |
| `rm -rf` command | Recursive delete |
| Retry count ≥ 3 | System is stuck, needs human judgment |

**What happens technically:**

```
Orchestrator thread           TUI (main thread)
─────────────────             ─────────────────
orchestrator.stream()
  → graph hits interrupt_on
  → graph pauses

hitl.request_approval(        app.show_approval_panel()
  "open_pr",                    → ApprovalPanel becomes visible
  {pr_title, pr_body}           → Input field appears
)
                              User types "a" + Enter

                              on_input_submitted()
                                → hitl.resolve(approved=True)
threading.Event.set()
hitl.request_approval()
  → returns True

orchestrator resumes
  → open_pr executes
```

The **key insight:** Two threads are involved. The AI thread blocks on a `threading.Event`. The TUI (UI) thread sets that event when you respond. They never share mutable state directly — the Event acts as a safe handshake.

---

### Step 8 — PRAgent Opens the Pull Request

```
PRAgent creates:
  Branch: codepilot/issue-42-fix-login-crash
  
  Commit message:
    fix(#42): guard against empty password in auth.validate()
    
    - Add null-check before calling .lower() on password param
    - Add test_empty_password_returns_401 to test suite
    
    Closes #42
    Trace-Id: a1b2c3d4

  PR body includes:
    - Issue summary
    - Approach taken
    - Files changed
    - Test results (12 passed, 0 failed)
    - "Closes #42"
    - Labels: codepilot-generated, needs-review
    - Reviewer: issue reporter's GitHub login
```

---

### Step 9 — Memory Update

After success the Orchestrator calls:

```python
add_lesson(
    repo="org/myrepo",
    issue_type="bug_fix",
    approach="add null-check before string method call",
    outcome="success",
    files=["src/auth.py", "tests/test_auth.py"]
)
```

This record is stored and retrieved the next time a similar bug_fix issue arrives.

---

## 5. State Machine

Every task progresses through exactly these states in order. Going backwards is not allowed — if something goes wrong it jumps directly to FAILED.

```
              ┌─────────┐
  Issue       │ TRIAGED │
  picked up   └────┬────┘
                   │
                   ▼
             ┌──────────┐
             │EXPLORING │  ← RepoExplorer running
             └────┬─────┘
                  │
                  ▼
           ┌─────────────┐
           │IMPLEMENTING │  ← Coder editing files
           └──────┬──────┘     (can loop back here on test failure)
                  │
                  ▼
            ┌─────────┐
            │ TESTING │  ← TestAgent running full suite
            └────┬────┘
                 │
                 ▼
           ┌───────────┐
           │ PR_OPENED │  ← PRAgent created the PR
           └─────┬─────┘
                 │
         ┌───────┴────────┐
         ▼                ▼
      ┌──────┐        ┌────────┐
      │ DONE │        │ FAILED │
      └──────┘        └────────┘
```

Invalid transitions (e.g. DONE → EXPLORING) raise an `InvalidTransition` exception. This prevents bugs where an agent tries to restart completed work.

---

## 6. The Safety Layer in Detail

### ShellGuard — Command Screening

Every shell command the AI wants to run is checked against a rule table **before** execution:

```
Command: ":(){:|:&};:"
    │
    ▼
ShellGuard.validate()
    │
    ├─ rule "fork_bomb" matches (regex: :(\s*)\(\s*\)\s*\{)
    │
    ▼
Decision: BLOCK → raises PermissionError("fork_bomb: fork bomb — ...")
    (no human can override a BLOCK)
```

```
Command: "rm -rf ./build_artifacts"
    │
    ▼
ShellGuard.validate()
    │
    ├─ rule "rm_rf" matches
    │
    ▼
Decision: HITL → raises PermissionError("HITL: rm_rf requires approval")
    (human can approve, then command executes)
```

```
Command: "pytest tests/"
    │
    ▼
ShellGuard.validate()
    │
    └─ no rules match
    │
    ▼
Decision: ALLOWED → command runs in LocalSandbox
```

**Two-tier model:**
- `BLOCK` = hard no. Not even a human can approve it. Reserved for catastrophic commands (fork bomb, disk wipe, raw device write).
- `HITL` = pause and ask a human. Used for risky-but-sometimes-necessary commands (rm -rf, git push, curl, sudo).

### LocalSandbox — Filesystem Containment

All file operations happen inside a temporary directory. If any path tries to escape (e.g. `../../etc/passwd`), the sandbox raises `SandboxEscapeError` before touching the filesystem.

---

## 7. Memory in Three Tiers

| Tier | Lives where | Cleared when | Used for |
|------|-------------|--------------|----------|
| Working Memory | RAM (Python dict) | Task reaches DONE/FAILED | Current task state, file list, retry count |
| Episodic Store | Process memory (LangGraph InMemoryStore) | Process restart | Session summaries, recent task outcomes |
| Semantic Store | Qdrant (vector database) | Never | Cross-session lessons, cosine-similarity search |

Think of it as: **sticky notes** (working) vs **notebook** (episodic) vs **reference library** (semantic).

---

## 8. What You See in the Terminal

When you run `codepilot run`, a 3-row dashboard appears with a One Dark color theme:

```
┌──────────────────────┬──────────────────────────┐  ← row 1 (short)
│ GitHub Issues        │ Active Task               │
│                      │                           │
│ ◉ #42 Fix login     │ Issue #42: Fix login      │
│ ● #43 Add search    │ ◉ IMPLEMENTING             │  ← state badge (yellow)
│ ✓ #41 Update docs   │ Agent: Coder               │
│                      │ Skill: bug_fix             │
│                      │ Retry: 0/3                 │
│                      │ [coder] working… (18s)     │  ← heartbeat (live)
├──────────────────────┴──────────────────────────┤  ← row 2 (tallest)
│ Activity Log                                     │
│                                                  │
│ 14:22:01 [Orchestrator] Picked up #42           │  ← grey (default)
│ 14:22:05 [→] task → repo_explorer               │
│ 14:22:31 [repo_explorer] done (26s) — 42 files  │  ← green (done)
│ 14:22:32 [coder] working… (18s)                  │  ← yellow (working)
├──────────────────────────────────────────────────┤  ← row 3 (hidden until HITL)
│ ⚠ APPROVAL REQUIRED — open_pr                   │  ← green border + bg
│ Open PR → main (#42 Fix login crash)             │
│ [A] Approve   [R] Reject                         │
│ > approve_                                       │
└──────────────────────────────────────────────────┘
```

**Panel details:**

| Panel | Location | Updates |
|-------|----------|---------|
| GitHub Issues | Top-left (short) | Real-time — each row colored by state (grey/blue/yellow/purple/teal/green/red) |
| Active Task | Top-right (short) | State badge color tracks task state; border color changes per state; heartbeat line shows running agent |
| Activity Log | Middle (full-width, tallest) | Streaming — each line timestamped and color-coded by keyword |
| Approval | Bottom (full-width, hidden) | Appears with green border when HITL fires; disappears after approve/reject |

**State colors** (used in Issues rows, Active Task border, log lines):

| State | Color | Meaning |
|-------|-------|---------|
| TRIAGED | grey | Issue queued |
| EXPLORING | blue | RepoExplorer mapping files |
| IMPLEMENTING | yellow | Coder writing code |
| TESTING | purple | TestAgent running suite |
| PR_OPENED | teal | PR created |
| DONE | green | Complete |
| FAILED | red | Unrecoverable error |

**Keyboard shortcuts:**
- `q` — quit
- `l` — toggle the event log panel
- `i` — open prompt to type a free-form coding task (not tied to a GitHub issue)
- `s` — skip the current issue

---

## 9. The Tool System — How Agents Act

Agents don't directly call Python functions. They call **tools** — Python functions decorated with `@tool` that the LangGraph framework exposes to the LLM.

```python
@tool
def classify_issue(title: str, body: str, labels: list[str]) -> str:
    """Return the issue type string."""
    ...
```

When the LLM decides to classify an issue, it generates a JSON blob:
```json
{"name": "classify_issue", "args": {"title": "...", "body": "...", "labels": [...]}}
```

LangGraph deserializes this, calls the Python function, and returns the result as the next message in the conversation. The LLM never directly executes code — it only requests tool calls.

This is why guardrails work: the ShellGuard sits inside the tool that executes shell commands. The LLM can never bypass it because the LLM never directly runs a shell — it can only ask the `execute` tool to run a shell command, and that tool always goes through the guard.

---

## 10. Subagents — Agents Spawning Agents

The Orchestrator is a top-level LangGraph agent. When it calls `task("coder", ...)`, DeepAgents spins up a fresh Coder agent with:
- Its own system prompt
- A restricted tool set
- Its own filesystem permissions (defined in `subagents.py`)
- No access to the parent Orchestrator's conversation history

This isolation matters. The Coder can't accidentally read the Orchestrator's deliberation, can't call GitHub tools directly, and can't write outside `/sandbox/`. Each subagent is a separate LLM conversation with a narrow scope.

```
Orchestrator
│  tools: classify_issue, list_open_issues, query_lessons, add_lesson,
│          get_issue, create_branch, commit_files, open_pr, + GitHub toolkit
│  can spawn: repo_explorer, coder, pr_agent
│
├── repo_explorer
│     tools: build_repo_map, retrieve_relevant_files, load_cached_repo_map, cache_repo_map
│     write: DENIED everywhere
│
├── coder
│     tools: run_tests (+ built-in read_file/edit_file/execute from DeepAgents)
│     write: /sandbox/** only
│     can spawn: test_agent
│     │
│     └── test_agent
│           tools: run_tests, parse_test_output
│           write: /sandbox/** only
│
└── pr_agent
      tools: inherited GitHub tools from orchestrator
      write: DENIED (read /sandbox/** only)
```

---

## 11. Configuration and Environment

All settings come from environment variables (or a `.env` file). The system validates them at startup:

```
GITHUB_APP_ID          — GitHub App identifier
GITHUB_APP_PRIVATE_KEY — PEM key for JWT auth
GITHUB_TOKEN           — optional personal token (used for IssuePoller)
REPO_FULL_NAME         — e.g. "myorg/myrepo"
ANTHROPIC_API_KEY      — at least one LLM key required
OPENAI_API_KEY         — alternative LLM key

POLL_INTERVAL_MIN      — how often to check for new issues (default 5)
MAX_RETRIES            — max Coder retries before HITL (default 3)
COMPLEXITY_THRESHOLD   — skip issues above this complexity score (default 6)
```

Run `codepilot doctor` to validate all settings before starting.

---

## 12. Running It

```bash
# 1. Install
pip install -e ".[dev]"

# 2. Copy and fill in environment
cp .env.example .env
# edit .env with your keys

# 3. Validate settings
python -m codepilot doctor

# 4. Run
python -m codepilot run
```

The TUI starts, the background thread begins polling GitHub, and issues start flowing through the pipeline.

---

## 13. How the Pieces Are Tested

The project has 744 unit tests. Key patterns:

**Mocking external boundaries only:**
```python
# Good: mock GitHub API, not internal logic
monkeypatch.setattr(GitHubClient, "list_open_issues", lambda *a, **kw: [fake_issue])

# The classifier, guardrails, sandbox — all tested with real logic, no mocks
```

**Sandbox tests run real subprocesses:**
```python
result = sandbox.execute('python -c "print(\'hello\')"')
assert "hello" in result.stdout
```

**Guardrail tests verify exact rule names in error messages:**
```python
with pytest.raises(PermissionError) as exc_info:
    sandbox.execute(":(){:|:&};:")
assert "fork_bomb" in str(exc_info.value)
```

Run all tests: `python tasks.py test`
Run with coverage gate (85%): `python tasks.py test-cov`

---

## 14. Glossary

| Term | Meaning |
|------|---------|
| **Orchestrator** | The top-level LangGraph agent. Coordinates all subagents. |
| **Subagent** | A child agent spawned by the Orchestrator with limited scope. |
| **HITL** | Human-in-the-Loop. A pause point where a human must approve before work continues. |
| **Skill** | A YAML file describing how to handle a specific task type (bug_fix, feature_addition, etc.). |
| **Sandbox** | A temporary directory where all code changes live until PRAgent commits them. |
| **ShellGuard** | Screens every shell command before it runs. BLOCK = never, HITL = ask first. |
| **WorkingMemory** | In-process state for one task. Cleared when task finishes. |
| **EpisodicStore** | Records what happened in each task session. |
| **SemanticStore** | Qdrant vector DB. Searches past lessons by meaning, not exact keyword. |
| **IssuePoller** | Background loop that fetches new GitHub issues on a timer. |
| **RepoMap** | JSON index of every file + symbol in the repo. Built once, cached by Git SHA. |
| **TUI** | Terminal User Interface — the 3-row dashboard (Issues + Active Task on top, full-width log, Approval on demand) seen when running `codepilot run`. |
| **LangGraph** | The graph-execution framework that runs agents as state machines. |
| **DeepAgents** | The library that wraps LangGraph with `create_deep_agent()`, subagent spawning, and `FilesystemPermission`. |
| **`@tool`** | A Python decorator that makes a function callable by the LLM via JSON. |
| **threading.Event** | A synchronization primitive. The HITL coordinator uses one to block the AI thread until you respond. |
