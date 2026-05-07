# Phase 2 — Steering Doc: Memory Tiers

**Status:** complete
**Owner:** platform / agents
**Depends on:** Phase 0 (Settings), Phase 0.5 (Logging — for trace_id propagation)
**Unblocks:** Phase 6 (Repo Explorer — uses semantic store), Phase 7 (Coder — reads working memory), Phase 10 (Orchestrator — wires all 3 tiers)

---

## Goal

Three memory tiers, each with a clear lifetime and a single purpose:

- **Working** (in-process, per-task) — current state machine, file list, diff, retries. Cleared on terminal.
- **Episodic** (cross-task in one process; persistable via LangGraph store) — what was attempted, what passed/failed. Read at startup to skip recently-failed issues.
- **Semantic** (durable, queryable, cross-session) — lessons from successful merges. Searched before each task to inject "we've seen this before" context.

Every later phase reads or writes through these stores. No agent invents its own state container.

## Deliverables

| Artifact | Path | Purpose |
|---|---|---|
| Working memory + state machine | `codepilot/memory/state.py` | `TaskState`, `TRANSITIONS`, `WorkingMemory`, `WorkingMemoryRegistry`, `InvalidTransition` |
| Episodic store | `codepilot/memory/episodic.py` | `EpisodicStore` over LangGraph `BaseStore`, `SessionSummary`, `TaskOutcome` |
| Semantic store | `codepilot/memory/semantic.py` | `SemanticStore` over Qdrant, `Lesson`, `LessonHit` |
| Embedding layer | `codepilot/memory/embeddings.py` | `EmbeddingProvider` Protocol, `OpenAIEmbeddingProvider` (batching+retry+token-aware cost), `CachingEmbeddingProvider` (LRU+sqlite disk), `DeterministicEmbeddingProvider` (tests), `build_default_provider()` factory; legacy `EmbedFn` + `deterministic_embed` retained |
| Tests | `tests/unit/test_{working_memory,episodic,embeddings,semantic}.py` | 71 tests |

## Exit Criteria

- Every state-machine edge enforced; illegal transition raises `InvalidTransition`.
- Episodic round-trip: write session → read back → query "recently failed issue ids" returns expected set.
- Semantic round-trip in Qdrant `:memory:`: 4 seeded lessons, `query()` returns top-K with cosine scores; `repo` and `issue_type` filters narrow the result set; combined filters AND together.
- Embedding pluggable: `deterministic_embed` for tests, `make_openai_embed` lazy-imports OpenAI for production.
- Embedding layer is production-grade: `EmbeddingProvider` Protocol; `OpenAIEmbeddingProvider` batches up to N texts per call, retries transient errors with full-jitter exponential backoff, counts tokens via tiktoken, logs `embed.batch` with USD estimate per call, supports both sync + async; `CachingEmbeddingProvider` wraps any provider with thread-safe LRU + optional sqlite disk cache (keyed by `model + sha256(text)`); factory `build_default_provider()` wires everything from settings, falls back to `DeterministicEmbeddingProvider` when no LLM key is available.
- `pytest` green: 224 tests passing.

---

## Files

### Source

**`codepilot/memory/__init__.py`**
Public surface. Re-exports the three tier APIs (`WorkingMemory`, `WorkingMemoryRegistry`, `TaskState`, `EpisodicStore`, `SessionSummary`, `TaskOutcome`, `SemanticStore`, `Lesson`, `LessonHit`) plus embedding helpers (`EmbedFn`, `deterministic_embed`, `make_openai_embed`) and helper utilities (`new_session_id`, `now_utc`). Callers import only from `codepilot.memory`.

**`codepilot/memory/state.py`**
Working memory + state machine.
- `TaskState` enum: `TRIAGED, EXPLORING, IMPLEMENTING, TESTING, PR_OPENED, DONE, FAILED`.
- `TRANSITIONS: dict[TaskState, frozenset[TaskState]]` — allowed forward edges. `IMPLEMENTING → IMPLEMENTING` allowed (coder retry). `TESTING → IMPLEMENTING` allowed (test failure bounce). Every state can hop to `FAILED`. `DONE` and `FAILED` are terminal (empty edge sets).
- `TestRunSummary` — Pydantic model for test results (`passed`, `failed`, `framework`, `failures`). `__test__ = False` to keep pytest from collecting it.
- `WorkingMemory` — Pydantic model. Carries `issue_id`, `repo`, `trace_id`, `task_type`, current `state`, `repo_map_path`, `relevant_files`, `proposed_diff`, `test_results`, `retry_count`, `notes`. Methods: `transition(target)` validates against `TRANSITIONS`; `fail(reason)` jumps to `FAILED` with a note (idempotent on terminal); `is_terminal()`, `bump_retry()`. `for_subagent()` returns a snapshot dict EXCLUDING `proposed_diff` and `test_results` — those are big and live in the working set, not in the prompt.
- `WorkingMemoryRegistry` — in-process map of `issue_id → WorkingMemory`. `open()` creates and rejects double-open. `close()` requires terminal state (refusing to close a live task is a load-bearing safety check).
- `InvalidTransition(ValueError)` — raised by `transition()` and `close()` on illegal moves.

**`codepilot/memory/episodic.py`**
Cross-task / cross-session record-keeper.
- Two LangGraph store namespaces: `("codepilot", "sessions")` and `("codepilot", "tasks")`.
- `TaskOutcome` model — `issue_id`, `repo`, `task_type`, `files_modified`, `outcome` (`DONE`/`FAILED`), `duration_ms`, `pr_number`, `note`. One per attempted issue.
- `SessionSummary` model — `session_id`, `started_at`, `ended_at`, `tasks: list[TaskOutcome]`. Convenience properties `attempted_issue_ids`, `failed_issue_ids`.
- `EpisodicStore` wraps `BaseStore` (defaults to `InMemoryStore`).
  - `record_task(session_id, outcome)` → puts a per-task record under namespaced key `"{session_id}:{issue_id}"`.
  - `task_records(session_id)` → searches the task namespace, filters by key prefix.
  - `write_session(summary)` / `get_session(id)` — round-trip session summaries.
  - `recent_sessions(n=3)` — fetches all, sorts by `ended_at` desc, slices.
  - `recently_failed_issue_ids(n=3)` — set union of failed IDs across the last `n` sessions.
- `new_session_id()` (uuid hex), `now_utc()` helpers.

**`codepilot/memory/embeddings.py`**
Production embedding layer. Backwards-compatible: legacy `EmbedFn` callable type + `deterministic_embed` callable + `make_openai_embed` factory all retained as a compatibility shim.

- `EmbeddingProvider` (`runtime_checkable` Protocol) — exposes `model_name`, `dim`, `embed`, `embed_batch`, `aembed`, `aembed_batch`. Single contract every consumer talks to.
- `_BaseProvider` — concrete defaults: `aembed*` route through `asyncio.to_thread`; single-text `embed` delegates to `embed_batch`. Subclasses override only what they need.
- `DeterministicEmbeddingProvider(dim=128)` — wraps `deterministic_embed`. `model_name` = `"deterministic-sha256"`. Used in every offline test and as the production fallback when no LLM key is configured.
- `OpenAIEmbeddingProvider(*, model, dim, api_key, client, async_client, max_batch, retry, encoding_name, sleep, usd_per_1k)`:
  - **Batching**: splits inputs into chunks of `max_batch` (default 128); one network call per chunk.
  - **Retry**: full-jitter exponential backoff (`_RetryConfig(max_attempts=5, base=0.5, cap=30.0)`). `_is_transient` matches `RateLimitError`, `APITimeoutError`, `APIConnectionError`, `InternalServerError`, `ServiceUnavailableError` by class name + HTTP 429 / 5xx by `status_code`. Non-transient errors bubble immediately.
  - **Dimensions param**: only sent when caller's `dim` differs from the model's native dim — avoids "dimensions not supported" errors on legacy models like `text-embedding-ada-002`.
  - **Token counting + cost**: lazy-loads tiktoken; falls back to `len(text)//4` when missing. After every successful batch logs `embed.batch` event with `model`, `count`, `tokens`, `usd` (from `_OPENAI_USD_PER_1K_TOKENS` table), `latency_ms`, `attempts`.
  - **Async**: `aembed_batch` uses `AsyncOpenAI` directly (no thread offload); same retry semantics with `await asyncio.sleep`.
  - **Lazy clients**: only constructs `OpenAI` / `AsyncOpenAI` on first call so tests can pass an injected `client` and `async_client` without importing the SDK.
- `_RetryConfig` — slots-based config struct with `backoff(attempt)` returning capped exponential value times `(0.5 + rng())` for jitter. RNG injectable for deterministic tests.
- `CachingEmbeddingProvider(inner, max_items=10_000, disk_path=None)`:
  - **Thread-safe LRU** via `OrderedDict` + `threading.Lock`. Cache key = `sha256(model_name + ":" + text)` so models don't collide.
  - **Optional sqlite disk cache** (`_DiskKV`) — WAL-mode sqlite, `INSERT OR REPLACE` upserts, single-writer/multi-reader safe. Disk hits warm the in-memory LRU on read.
  - **Partial-hit batching**: separates hits from misses, calls `inner.embed_batch` only on misses, stitches results back into original order. One round trip per batch instead of one per text.
  - Logs `embed.cache` at debug level with `hits`, `misses`, `total`.
- `build_default_provider(*, settings=None, use_cache=True, disk_cache_path=None)` — factory:
  - Reads `Settings` if not supplied; resolves `openai_api_key`.
  - No key → `DeterministicEmbeddingProvider` and a `embed.fallback.deterministic` warning log (lets `doctor` work offline without surprises).
  - Key present → `OpenAIEmbeddingProvider` wrapped in `CachingEmbeddingProvider` if `use_cache`, naked otherwise.
- Cost tables (`_OPENAI_USD_PER_1K_TOKENS`, `_OPENAI_NATIVE_DIMS`) — centralised so a model-pricing change is a one-line edit.
- Legacy: `make_openai_embed(model)` returns an `EmbedFn` backed by `OpenAIEmbeddingProvider.embed` so existing call sites keep working.

**`codepilot/memory/semantic.py`**
Qdrant-backed lesson store.
- `Lesson` (frozen) — `id`, `repo`, `issue_type`, `files`, `approach`, `outcome`, `summary`, `created_at`. `LessonHit` — `lesson` + `score`.
- `SemanticStore(client=None, collection="lessons", embed_fn=None, vector_size=128)`. Defaults: `QdrantClient(":memory:")`, `deterministic_embed`. `_ensure_collection()` creates with `Distance.COSINE` if absent (idempotent).
- `add_lesson(*, repo, issue_type, files, approach, outcome, summary, lesson_id=None)` → mints UUID id, builds `Lesson`, embeds via `_embed_text(lesson)` (composes summary + issue_type + approach + files), `upsert` into Qdrant with full lesson as payload.
- `query(task_desc, *, k=3, repo=None, issue_type=None)` — `query_points` with cosine, optional payload filter (`repo` AND `issue_type`). Returns top-K `LessonHit`s sorted by score desc.
- `_build_filter` composes `Filter(must=[FieldCondition(...)])` from optional params; returns `None` when neither set.
- `count()`, `delete_collection()` — maintenance.
- `_embed_text(lesson)` — kept as a function so the embedding text strategy is testable in isolation.

### Tests (46 new)

**`tests/unit/test_working_memory.py`** (16)
- `TestConstruction` — defaults, `retry_count < 0` rejected by Pydantic.
- `TestTransitions` — happy-path edges parametrized; `IMPLEMENTING → IMPLEMENTING` allowed, other self-loops illegal; `TESTING → IMPLEMENTING` allowed; large parametrized set of illegal edges raises; terminal blocks all moves; `fail()` works from any non-terminal; `fail()` no-op on terminal.
- `TestTransitionsTable` — every `TaskState` value has an entry in `TRANSITIONS`.
- `TestSubagentSnapshot` — `for_subagent()` excludes `proposed_diff` and `test_results`; includes `relevant_files` and serialised state value.
- `TestRegistry` — `open` / `get` / `close` round trip; double-open rejected; closing a non-terminal raises; closing unknown is silent.

**`tests/unit/test_episodic.py`** (8)
- `TestTaskRecords` — record-and-read; isolation across sessions via key prefix.
- `TestSessionRoundtrip` — write/get; unknown session returns `None`.
- `TestRecentSessions` — sorted by `ended_at` desc; clamped when fewer than `n`.
- `TestRecentlyFailed` — failures collected only from the windowed sessions; all-`DONE` window returns empty.

**`tests/unit/test_embeddings.py`** (30)
- `TestDeterministic` (8) — legacy callable: dim default + custom, stable, distinct inputs differ, unit norm; provider wrapper: implements Protocol, batch shape, async path.
- `TestOpenAIBatching` (4) — single call when ≤ `max_batch`; chunking when above; empty input returns empty; single-text path uses batch under the hood.
- `TestOpenAIRetry` (3) — retries-then-succeeds for `RateLimitError`-like transients; non-transient (`ValueError`) raises immediately; exhausting attempts re-raises last transient.
- `TestOpenAIDimensionsParam` (2) — sends `dimensions` when caller dim ≠ native; omits it on native dim.
- `TestOpenAITokenCount` (1) — tiktoken path produces > 0.
- `TestOpenAIAsync` (1) — `aembed_batch` uses `AsyncOpenAI`, batching applies.
- `TestCaching` (5) — repeated text → 1 inner call; partial-hit batches only misses; LRU evicts oldest at `max_items`; sqlite disk cache survives across `CachingEmbeddingProvider` instances; cache key includes model name (different models → different cache).
- `TestFactory` (3) — no key → `DeterministicEmbeddingProvider`; key + `use_cache=True` → wrapped in `CachingEmbeddingProvider`; key + `use_cache=False` → bare `OpenAIEmbeddingProvider`.
- `TestSemanticStoreWithProvider` (3) — passing `provider` propagates to writes + queries; passing both `provider` and `embed_fn` raises; legacy `embed_fn` path still works.

**`tests/unit/test_semantic.py`** (10)
- `TestCollectionLifecycle` — collection auto-created; empty `count()`.
- `TestAddAndQuery` — top-K respected; scores sorted descending; `repo` filter isolates; `issue_type` filter isolates; combined filters intersect.
- `TestSimilarityShape` — matching-summary lesson outranks unrelated lesson for the same query.
- `TestPersistencePerInstance` — count after seed.
- `TestCustomLessonId` — caller-supplied id used.

---

## Architecture

```
                        Issue picked up (Phase 1)
                                 │
                                 ▼
            ┌───────────────────────────────────────┐
 startup ─▶ │  EpisodicStore.recent_sessions(3)     │  cross-session reads
            │  → recently_failed_issue_ids          │
            └───────────────┬───────────────────────┘
                            │ skip if issue id in set
                            ▼
            ┌───────────────────────────────────────┐
            │  SemanticStore.query(task_desc, k=3)  │  inject lessons
            └───────────────┬───────────────────────┘
                            ▼
            ┌───────────────────────────────────────┐
            │  WorkingMemoryRegistry.open(issue_id) │  per-task state
            │  state machine drives subagent fan-out│
            └───────────────┬───────────────────────┘
                            │ on terminal
                            ▼
            ┌───────────────────────────────────────┐
            │  EpisodicStore.record_task(...)       │  log this attempt
            │  if DONE: SemanticStore.add_lesson(.) │  promote to durable
            │  WorkingMemoryRegistry.close(.)       │  free in-process slot
            └───────────────────────────────────────┘
```

Each tier is one source of truth for one question:
- "What's happening right now?" → working
- "What did we already try this run?" → episodic
- "What worked last time on a similar task?" → semantic

---

## FAQ

### Q1. Why three tiers instead of one durable store?
Lifetime and read frequency differ by orders of magnitude.
- Working memory mutates every few seconds; persisting it would be wasted I/O.
- Episodic memory is appended once per task; tiny.
- Semantic memory is appended once per *successful merge* and read on every new task; needs vector index.
One store would force the slowest operations to the dominant tier.

### Q2. Why a state-machine enum instead of a plain string?
String states drift (typos, casing, "implementing" vs "Implementing"). Every comparison becomes a possible silent-pass bug. `TaskState` plus a hard-coded `TRANSITIONS` table forces every move through one validator. Tests parametrize the whole edge set in two lines.

### Q3. Why is `IMPLEMENTING → IMPLEMENTING` legal but no other self-loop?
The Coder retries inside the same state — read, edit, execute, fail, edit again. Modeling each retry as a no-op self-transition (with `bump_retry()` recording the attempt) keeps the timeline visible. Other self-loops have no real meaning; allowing them would mask logic bugs.

### Q4. Why does `TESTING → IMPLEMENTING` exist?
Test failure bounces back to the Coder for another fix attempt. Without this edge the only way to retry would be to fail the whole task — unusable, since the assignment limits retries to 3 before giving up.

### Q5. Why does `for_subagent()` strip `proposed_diff` and `test_results`?
DeepAgents' context engineering rule: subagents read files on-demand, the orchestrator passes paths. The diff and test results are large blobs; sending them in every spawn prompt would balloon prompt cost and crowd out actual instructions. The Coder reads them via `read_file` if and when it needs to.

### Q6. Why use `WorkingMemoryRegistry` instead of a global dict?
Two reasons:
1. **Centralized invariants.** Double-open detection, terminal-state-required-to-close, length introspection — all enforced in one place.
2. **Substitutability.** Phase 10 may swap in a registry that fans out to multiple workers. The orchestrator's interface stays the same.

### Q7. Why LangGraph's `BaseStore` for episodic memory instead of a plain dict or sqlite?
LangGraph already ships the abstraction we want — namespaced put/get/search across pluggable backends (in-memory, Postgres). The orchestrator runs on LangGraph anyway. Using its store means episodic memory can graduate from `InMemoryStore` to a Postgres-backed store without changing call sites.

### Q8. Why store both per-task records AND session summaries?
Different read patterns:
- Per-task records support "did this exact issue get attempted in this session?" — fine-grained dedupe.
- Session summaries support "show me the last 3 runs of CodePilot." — rollup view used by `recent_sessions`.
Computing one from the other on demand wastes reads at scale; storing both is cheap.

### Q9. Why Qdrant instead of Chroma / FAISS / pgvector?
Per the user's steer earlier in this project. Practical wins: ships a `:memory:` mode for tests (no docker), supports payload filters (we use `repo` and `issue_type`), and has a healthy ops story (server mode, k8s operator) for production.

### Q10. Why does `_embed_text` compose summary + issue_type + approach + files instead of just embedding `summary`?
Lessons are queried by *task descriptions*, which won't match summary phrasing exactly. Including `approach` and `files` widens the surface for similarity hits — e.g. a query mentioning "auth middleware" will rank lessons whose `files` list a path under `auth/` even when the summary uses different words.

### Q11. Why `deterministic_embed` instead of mocking the OpenAI client?
Mocks fix one call shape. A bug in our composition function (`_embed_text`) would still pass against a mock that returns identical fixed vectors. The deterministic embed is a real function that produces real vectors with real cosine geometry — it tests our pipeline end-to-end on the same inputs production would see.

### Q12. Why `lesson_id` defaults to `uuid.uuid4().hex` but accepts a caller value?
Callers occasionally need a stable id (e.g. "this lesson is keyed off issue 42 on repo X" → idempotent ingestion). Defaulting to UUID gives uniqueness; allowing override gives idempotency. Cheap to support both.

### Q13. Why does `WorkingMemory` carry `trace_id`?
Every log line and every audit row needs one. Embedding it in the working memory means subagents that receive the snapshot can call `bind_task(..., trace_id=wm.trace_id)` to rejoin the trace context if they're on a different process or thread. Without it, child traces fork.

### Q14. Why is `ensure_collection` idempotent instead of asserting absence?
Multiple `SemanticStore` instances in the same process (tests, repl, recovery flows) share a Qdrant client. Asserting absence would force coordination between them — overkill for "make sure this exists." Idempotent create is the simpler primitive.

### Q15. Why use `query_points` instead of `search` (which the plan listed)?
`search` is deprecated in `qdrant-client ≥ 1.10`. `query_points` is the supported API and returns a `QueryResponse` with `.points`. Functionally equivalent for our use case. Calling `search` would print a deprecation warning that bleeds into structured logs.

### Q16. Why does `recently_failed_issue_ids` use a window instead of "all time"?
The point is to avoid retrying *recently* failed issues — long-standing failures may have been fixed by humans or by code drift. A 3-session window matches the assignment's "last 3 session summaries" and stays bounded as the store grows.

### Q17. Why isn't there a "skill memory" tier?
Skills are static, code-shaped instructions (Phase 3). They don't accumulate at runtime — they ship with the binary. Treating them as a memory tier would imply they belong in a store; they belong on disk in `skills/definitions/`.

### Q18a. Why a Provider Protocol on top of `EmbedFn`?
`EmbedFn = Callable[[str], list[float]]` covers the *call*, not the *contract*. Production needs more than a call: model name (for cache keys + cost tables), dim (for collection sizing), batch path (for cost), async path (for the orchestrator), retry semantics. A Protocol surfaces all of those without locking us into a class hierarchy. `EmbedFn` is kept as a back-compat alias.

### Q18b. Why batch up to 128 texts per OpenAI call?
The embedding endpoint accepts arrays. A repo-explorer pass over 200 chunks takes 200 round trips at one-text-per-call vs ~2 round trips when batched. Latency drops 50–100x; cost stays the same. 128 is the conservative ceiling — OpenAI's hard limit is higher but per-request payload + token caps make 128 a stable choice.

### Q18c. Why full-jitter exponential backoff specifically?
Equal-spaced retries cause thundering herds when many workers hit the same rate limit window. `min(cap, base * 2^(attempt-1)) * (0.5 + rng())` spreads retry times across a window, smoothing out load and minimising total wall time for a recovering server. Same shape AWS recommends for SDK clients.

### Q18d. Why a sqlite disk cache instead of relying on OS file cache or a managed service?
- Embeddings are deterministic for a given (model, text) pair — perfect cache candidate.
- Repo-explorer summaries change rarely; recomputing across runs burns money and time.
- A sqlite file is single-process safe (WAL mode), survives restarts, requires zero ops.
- Avoids adding Redis as a dependency for what is fundamentally a key-value blob.

### Q18e. Why does the cache key include `model_name`?
`text-embedding-3-small` and `text-embedding-3-large` produce vectors with different dims and different geometry. Sharing a cache would corrupt search. Keying on `model_name + ":" + text` partitions automatically.

### Q18f. Why does `build_default_provider` fall back to deterministic when no LLM key is set?
`doctor` and basic smoke tests must run on a fresh checkout without API credentials. Failing closed (raise) would block onboarding; failing silently to a no-op (returns zero vectors) would corrupt search. Falling back to a deterministic-but-real provider gives us functional vectors that just aren't semantically meaningful — exactly what offline development needs.

### Q18g. Why log `embed.batch` with USD estimate per call?
Cost is the #1 production concern for any agent system. A live counter in structured logs lets `trace_cli <trace_id>` show "this task spent $0.03 on embeddings." Without it, cost surprises arrive at month-end via the OpenAI bill. The `_OPENAI_USD_PER_1K_TOKENS` table is the single point of update when prices change.

### Q19. Why does `_build_filter` return `None` when no filter conditions are present?
Qdrant's `query_points` distinguishes "no filter" from "empty filter." Passing an empty `Filter(must=[])` works on some versions and silently rejects all points on others. `None` is the contract for "match everything."

---

## Decisions Log

| # | Decision | Alternatives | Rationale |
|---|---|---|---|
| 1 | Three tiers (working / episodic / semantic) | one durable store | lifetimes + access frequencies disagree |
| 2 | `TaskState` enum + `TRANSITIONS` dict | string + ad hoc validation | exhaustive parametrization, single source |
| 3 | `IMPLEMENTING → IMPLEMENTING` self-loop allowed | model retry differently | preserves visible timeline of attempts |
| 4 | `for_subagent` excludes diff + test results | include everything | DeepAgents context-engineering rule |
| 5 | LangGraph `BaseStore` for episodic | sqlite, plain dict | swappable to Postgres without API change |
| 6 | Qdrant for semantic | Chroma, FAISS | user steer + payload filters + `:memory:` |
| 7 | Pluggable `EmbedFn` | hard-code OpenAI | offline tests; future ollama / sentence-transformers |
| 8 | `deterministic_embed` for tests | mock OpenAI | tests our pipeline, not just our doubles |
| 9 | `_embed_text` composes summary + meta | embed summary alone | broader query-time match surface |
| 10 | `query_points` not `search` | use deprecated API | future-proof, no deprecation noise |
| 11 | 3-session window for failed-id lookback | all-time | assignment spec + bounded growth |
| 12 | `EmbeddingProvider` Protocol w/ batch + async | flat `EmbedFn` only | production needs more than a single sync call |
| 13 | OpenAI batching, retries, token-aware cost logging | naive 1-call-per-text | order-of-magnitude latency + observable spend |
| 14 | sqlite-backed disk cache for embeddings | redis / memcached / none | survives restart, zero ops |
| 15 | Cache key = `sha256(model + ":" + text)` | text alone | model-mixing would corrupt cosine geometry |
| 16 | Deterministic fallback when no LLM key | hard fail | enables offline `doctor` + onboarding |

## Risks / Things to revisit

- **Episodic durability**: `InMemoryStore` loses data on process restart. Phase 13 should wire a Postgres-backed `BaseStore` if multi-host operation is needed.
- **Vector size mismatch**: `SemanticStore.vector_size` defaults to the provider's `dim`. Switching providers in-place (e.g. deterministic 128 → OpenAI 1536) requires recreating the collection; add a migration helper before flipping production.
- **No retention policy on lessons**: every successful merge becomes a lesson. After 6 months the corpus dwarfs context budgets. Add scoring + expiry in Phase 13.
- **Qdrant `:memory:` per `SemanticStore`**: each test instance gets its own client. Running 100 of these in parallel allocates a lot of in-memory shards — cap concurrency in CI if benchmarks bite.
- **`pr_number` on `TaskOutcome` is optional**: orchestrator must remember to set it on success; otherwise audit reconstruction misses the link. Phase 9 will wire this and add a test.
