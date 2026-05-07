# Phase 6 — Steering Doc: Repo Explorer Agent

**Status:** complete
**Owner:** agents / context-engineering
**Depends on:** Phase 2 (Memory — `WorkingMemory`, `TaskState`), Phase 5 (Sandbox — `LocalSandbox.write_file`), Phase 0.5 (Logging — `Event.REPO_MAP_BUILT`, `Event.FILES_RETRIEVED`)
**Unblocks:** Phase 7 (Coder — consumes `wm.relevant_files` and reads map from sandbox), Phase 8 (Test Agent — knows which test files to run), Phase 10 (Orchestrator — drives `RepoExplorerAgent.run` as first agent step)

---

## Goal

Give the downstream Coder agent a **focused view of the repository** — a token-budget-aware map of the file structure plus a ranked list of files most likely to need editing for a given issue. All without an LLM call, so the pipeline can function fully offline in tests and CI.

Two sub-problems:

1. **Map building** — walk the real repo tree, skip noise directories, extract top-level Python symbols with `ast`, honour a configurable token budget. Output: a `RepoMap` object whose `.to_text()` is an LLM-consumable string.
2. **File scoring** — rank entries against the issue body using keyword overlap (path tokens + symbol tokens) multiplied by a file-extension bonus. Output: an ordered `list[str]` of relative file paths.

The `RepoExplorerAgent` combines both, writes the map text into the sandbox, and populates `WorkingMemory.repo_map_path` / `relevant_files` before handing off to the Coder.

## Deliverables

| Artifact | Path | Purpose |
|---|---|---|
| Map builder | `codepilot/agents/repo_explorer/map.py` | `RepoMapEntry`, `RepoMap`, `_extract_symbols` |
| Scorer | `codepilot/agents/repo_explorer/scorer.py` | `score_files`, `_tokenise` |
| Agent | `codepilot/agents/repo_explorer/agent.py` | `RepoExplorerAgent` |
| Public API | `codepilot/agents/repo_explorer/__init__.py` | Re-exports all public symbols |
| Map tests | `tests/unit/test_repo_map.py` | 27 tests — symbol extraction, build, text output |
| Scorer tests | `tests/unit/test_file_scorer.py` | 18 tests — tokenisation, scoring, edge cases |
| Agent tests | `tests/unit/test_repo_explorer_agent.py` | 13 tests — state transitions, sandbox writes, ranking |

## Exit Criteria

- `_extract_symbols` returns top-level class + function names; skips nested; returns `[]` on syntax error.
- `RepoMap.build` includes `.py` and non-`.py` files; excludes `__pycache__`, `.git`, and other skip-listed dirs; entries sorted by path; first entry always included regardless of budget; `size_bytes` populated.
- `to_text()` renders `# Repo: <name>` header + one indented line per entry; symbol entries show `[sym1, sym2]`; empty map has header only.
- `score_files` returns `top_n` results; auth-related files rank above docs for login-related queries; empty/stop-word-only queries return first `n` entries in original order; ties broken alphabetically.
- `RepoExplorerAgent.run` transitions `TRIAGED → EXPLORING`; raises `InvalidTransition` from wrong state; writes `repo_map.txt` into sandbox; populates `wm.repo_map_path` and `wm.relevant_files`; returns the same `wm` object.
- `pytest` green: 620 passed, 2 skipped (symlink on Windows).

## Files

### Source

#### `codepilot/agents/repo_explorer/map.py`

**`_SKIP_DIRS`** — `frozenset` of directory names that are never walked: `.git`, `.hg`, `__pycache__`, `.mypy_cache`, `.venv`, `venv`, `node_modules`, `dist`, `build`, `.tox`, etc.

**`_CHARS_PER_TOKEN = 4`** — the conversion factor between character count and rough token count. Used to translate `max_tokens` into a character budget.

**`RepoMapEntry`** — frozen dataclass: `path: str` (forward-slash relative), `symbols: tuple[str, ...]`, `size_bytes: int`.

**`_extract_symbols(source_path)`** — reads a `.py` file with `ast.parse`, iterates top-level AST child nodes, collects names from `ClassDef`, `FunctionDef`, `AsyncFunctionDef`. Nested methods are not included. Returns `[]` on `SyntaxError`, `OSError`, or `ValueError` — never raises.

**`RepoMap`** — main class:
- `build(root, *, max_tokens=4000)` — resolves `root`, walks `root.rglob("*")` in sorted order, skips non-files and files inside skipped/hidden parent dirs, extracts symbols for `.py` files, estimates per-entry char cost, stops adding entries when budget exhausted (first entry always added regardless). Returns a `RepoMap` instance.
- `to_text()` — `"# Repo: {root.name}\n\n"` followed by one line per entry; symbol lines include `[sym, ...]` bracket annotation.
- `token_estimate()` — `len(to_text()) // 4`.
- `save(path)` — creates parent dirs, writes UTF-8.

#### `codepilot/agents/repo_explorer/scorer.py`

**`_STOP_WORDS`** — common English words removed before scoring to avoid false matches.

**`_EXT_BONUS`** — extension → float multiplier: `.py`/`.ts`/`.go`/`.rs` → 1.0; `.js` → 0.8; `.md` → 0.3; `.txt`/`.json`/`.yaml` → 0.2; unknown → 0.5.

**`_tokenise(text)`** — `re.findall(r"[a-z0-9]+", text.lower())` minus stop words minus single-character tokens.

**`score_files(entries, *, query, top_n=20)`**:
1. Tokenise query; if empty (or all stop words), return first `top_n` entries in order.
2. For each entry: compute `path_tokens` from the path string; `sym_tokens` from all symbol names.
3. `kw_score = 2 × (query tokens in path) + 1 × (query tokens in symbols)`.
4. `total = kw_score × (1 + ext_bonus)` if `kw_score > 0` else `0.0`.
5. Sort by `(-total, path)` for deterministic ties; return top `n` paths.

#### `codepilot/agents/repo_explorer/agent.py`

**`RepoExplorerAgent`**:
- `__init__(sandbox, *, max_tokens=4000, top_n_files=20)` — stores sandbox reference and tuning params.
- `run(wm, repo_root, issue_body)`:
  1. `wm.transition(TaskState.EXPLORING)` — raises `InvalidTransition` if state is wrong; caller responsibility.
  2. `RepoMap.build(repo_root, max_tokens=...)` — pure, no side effects.
  3. `score_files(repo_map.entries, query=issue_body, top_n=...)`.
  4. `sandbox.write_file("repo_map.txt", map_text)`.
  5. Sets `wm.repo_map_path = "repo_map.txt"` and `wm.relevant_files = relevant`.
  6. Emits `Event.REPO_MAP_BUILT` and `Event.FILES_RETRIEVED` via structlog.
  7. Returns `wm`.

#### `codepilot/agents/repo_explorer/__init__.py`

Re-exports: `RepoExplorerAgent`, `RepoMap`, `RepoMapEntry`, `score_files`.

### Tests

#### `tests/unit/test_repo_map.py` (27 tests)

Four test classes:

- `TestExtractSymbols` (7) — functions, classes, async, no nested, syntax error → `[]`, empty file → `[]`, mixed order.
- `TestRepoMapBuild` (12) — `.py` included, non-`.py` included, `__pycache__` excluded, `.git` excluded, symbols extracted, non-py symbols empty, entries sorted, empty dir → `[]`, `repo_root` stored, budget limits entries, budget=1 still has 1 entry, `size_bytes > 0`.
- `TestRepoMapText` (8) — header has repo name, paths in text, symbols in text, `token_estimate > 0`, empty map header-only, `save` writes file, `save` creates parent dirs, no-symbol entry has no `[`.

#### `tests/unit/test_file_scorer.py` (18 tests)

Two test classes:

- `TestTokenise` (6) — lowercases, stop words removed, alphanumeric split, single char removed, numbers kept, empty string → `[]`.
- `TestScoreFiles` (12) — auth file ranked high, `top_n` respected, all returned when `top_n > len`, empty query preserves order, symbol match scores, path match scores, `.py` over `.txt`, no entries → `[]`, results are strings, all entries in result when `top_n=len`, ties alphabetical, all-stop-word query = empty query.

#### `tests/unit/test_repo_explorer_agent.py` (13 tests)

One test class `TestRepoExplorerAgentRun`:

- State transitions to `EXPLORING`.
- `wm.repo_map_path` populated and file exists in sandbox.
- Repo map file has `# Repo:` header and contains a `.py` file path.
- `wm.relevant_files` is a non-empty list of strings.
- Auth files appear in top-3 for login query.
- `top_n_files=2` limits results to ≤ 2.
- Returns same `wm` object (mutates in place).
- `InvalidTransition` from wrong state (IMPLEMENTING).
- Empty repo still writes map file.
- `max_tokens=10` produces short map text (< 200 chars).

## Architecture

```
Orchestrator
    │
    └─► RepoExplorerAgent.run(wm, repo_root, issue_body)
            │
            ├─► wm.transition(EXPLORING)
            │
            ├─► RepoMap.build(repo_root, max_tokens=N)
            │       │
            │       └─► Path.rglob("*") sorted
            │               ├─► skip: __pycache__, .git, .venv, ...
            │               ├─► .py → _extract_symbols (ast.parse)
            │               └─► budget check → stop when full
            │
            ├─► score_files(entries, query=issue_body, top_n=N)
            │       │
            │       ├─► _tokenise(query) → query_tokens
            │       └─► per entry: kw_score × (1 + ext_bonus) → sort
            │
            ├─► sandbox.write_file("repo_map.txt", map_text)
            │
            ├─► wm.repo_map_path = "repo_map.txt"
            │   wm.relevant_files = [...]
            │
            └─► log REPO_MAP_BUILT, FILES_RETRIEVED
```

## FAQ

**Q: Why no LLM call for file selection?**
Keeping the Repo Explorer LLM-free gives deterministic, fast, zero-cost tests. The keyword scorer is good enough for finding auth files for an auth bug. A future `LLMRepoExplorerAgent` subclass can override `run` and use embeddings or a chat completion, but the default stays fast and testable.

**Q: Why use `ast` instead of regex for symbol extraction?**
Regex can't reliably distinguish top-level definitions from nested ones, or handle multi-line signatures. `ast.parse` is stdlib, handles all valid Python including async and decorators, and naturally gives the parent-child structure needed to exclude nested methods.

**Q: Why `_CHARS_PER_TOKEN = 4`?**
GPT-4 and Claude average ~4 chars per token for English + code. It's a rough estimate — off by 20% is fine for the repo map use case since `max_tokens` is set generously (default 4000). Exact tiktoken counting would add a heavy dependency.

**Q: Why weight path matches at +2 and symbol matches at +1?**
File paths are more informative: `src/auth.py` tells you the file is about auth even with no imports. Symbols are secondary — they confirm relevance but are less reliable (a utility file might define `authenticate` while the real auth module has a different name). The 2:1 ratio is empirically reasonable; it can be tuned.

**Q: Why is the first entry always included regardless of budget?**
`budget_chars = max_tokens * 4`. With `max_tokens=1`, budget = 4 chars — less than any file path. Without the "and entries" guard, the map would be empty every time. An empty map gives the Coder no context at all. One file is always better than none.

**Q: Why skip parent directories starting with `.`?**
Catches `.git`, `.github`, `.vscode`, `.idea`, `.env` directory variants (when named `.env`, the directory is hidden). The `_SKIP_DIRS` set covers named skip targets; the `.` prefix covers the long tail of tool-specific hidden directories.

**Q: Why `as_posix()` for the entry path?**
On Windows, `relative_to()` returns `Path` objects with backslashes. Using `as_posix()` normalises to forward slashes so the scorer's `re.findall(r"[a-z0-9]+", path)` and string comparisons work identically on all platforms. The Coder uses these paths to call `sandbox.write_file`, which accepts forward-slash paths.

**Q: Why store the map as a text file in the sandbox rather than in WorkingMemory?**
`WorkingMemory.for_subagent()` passes file paths, not content. Keeping large text blobs out of the serialised handoff keeps the subagent context small. The Coder reads the file from the sandbox when it needs the content.

## Decisions Log

| # | Decision | Alternatives considered | Rationale |
|---|---|---|---|
| 1 | Keyword scorer, no LLM | Embedding similarity; BM25 | Zero dependencies, deterministic tests, fast; LLM can be layered on top |
| 2 | `ast` for symbol extraction | `tree-sitter`; regex | Stdlib, handles all valid Python, parent-child structure for nested exclusion |
| 3 | 4 chars-per-token estimate | `tiktoken`; word count | No extra dependency; ±20% precision is fine for a map budget |
| 4 | Path score weight = 2, symbol = 1 | Equal weights; path-only | Path is more reliable signal; symbols refine, not replace |
| 5 | First entry always added | Fail if budget < any entry | Empty map = zero context for Coder; one entry is always better than none |
| 6 | `as_posix()` for entry paths | Native `Path` | Cross-platform forward-slash consistency for scorer regex and sandbox paths |
| 7 | Map saved to sandbox as `repo_map.txt` | In-memory string in `wm` | `for_subagent()` passes paths, not content; avoids large blobs in handoff dict |

## Risks / Things to Revisit

- **Keyword scorer false negatives**: A bug about `UserProfile.avatar` won't match `src/models/user.py` unless "user" appears in the query. LLM-based ranking in a future phase would handle semantic similarity.
- **Large repos exhaust budget silently**: With 10,000 files and `max_tokens=4000`, most files are silently dropped. Add a logged warning when budget is hit so operators know the map is truncated.
- **Symbol extraction for non-Python files**: TypeScript, Go, Rust codebases get no symbol metadata. The extension bonus partially compensates, but a multi-language symbol extractor (tree-sitter) would help.
- **`rglob("*")` on very large repos is slow**: Potentially tens of thousands of `stat()` calls. For repos > ~50k files, consider a `.gitignore`-aware walk or a pre-built file list from `git ls-files`.
- **Forward-slash assumption in Coder**: The Coder will receive `wm.relevant_files` as forward-slash paths. If it constructs absolute paths on Windows via simple string join, it needs to use `Path(...)` not string concatenation.
