import asyncio
import math
from pathlib import Path
from typing import Any

import pytest

from codepilot.memory.embeddings import (
    DEFAULT_DIM,
    CachingEmbeddingProvider,
    DeterministicEmbeddingProvider,
    EmbeddingProvider,
    OpenAIEmbeddingProvider,
    _RetryConfig,
    build_default_provider,
    deterministic_embed,
)


# ---------------------------------------------------------------------------
# Deterministic provider + legacy callable
# ---------------------------------------------------------------------------

class TestDeterministic:
    def test_dim(self) -> None:
        v = deterministic_embed("hello")
        assert len(v) == DEFAULT_DIM

    def test_stable(self) -> None:
        assert deterministic_embed("x") == deterministic_embed("x")

    def test_different_inputs_differ(self) -> None:
        assert deterministic_embed("a") != deterministic_embed("b")

    def test_unit_norm(self) -> None:
        v = deterministic_embed("hello")
        norm = math.sqrt(sum(x * x for x in v))
        assert abs(norm - 1.0) < 1e-6

    def test_custom_dim(self) -> None:
        v = deterministic_embed("hello", dim=64)
        assert len(v) == 64

    def test_provider_satisfies_protocol(self) -> None:
        p = DeterministicEmbeddingProvider()
        assert isinstance(p, EmbeddingProvider)
        assert p.model_name == "deterministic-sha256"
        assert p.dim == DEFAULT_DIM

    def test_provider_batch(self) -> None:
        p = DeterministicEmbeddingProvider(dim=32)
        out = p.embed_batch(["a", "b", "c"])
        assert len(out) == 3
        assert len(out[0]) == 32

    def test_provider_async(self) -> None:
        p = DeterministicEmbeddingProvider()

        async def run() -> list[list[float]]:
            return await p.aembed_batch(["a", "b"])

        result = asyncio.run(run())
        assert len(result) == 2


# ---------------------------------------------------------------------------
# OpenAI provider — tests use a fake client (no network)
# ---------------------------------------------------------------------------

class _FakeEmbObj:
    def __init__(self, embedding: list[float]) -> None:
        self.embedding = embedding


class _FakeResp:
    def __init__(self, vectors: list[list[float]]) -> None:
        self.data = [_FakeEmbObj(v) for v in vectors]


class _FakeEmbeddings:
    def __init__(self, parent: "_FakeOpenAI") -> None:
        self._parent = parent

    def create(self, *, model: str, input: list[str], **kw: Any) -> _FakeResp:
        self._parent.calls.append({"model": model, "input": list(input), **kw})
        if self._parent.fail_n > 0:
            self._parent.fail_n -= 1
            raise self._parent.fail_exc()  # noqa: TRY301
        return _FakeResp([deterministic_embed(t, dim=4) for t in input])


class _FakeOpenAI:
    def __init__(self, fail_n: int = 0,
                 fail_exc: Any = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_n = fail_n
        self.fail_exc = fail_exc or (lambda: RuntimeError("boom"))
        self.embeddings = _FakeEmbeddings(self)


class _FakeRateLimit(RuntimeError):
    """Mimics openai.RateLimitError name + status."""
    status_code = 429


_FakeRateLimit.__name__ = "RateLimitError"


class TestOpenAIBatching:
    def test_single_call_under_max_batch(self) -> None:
        fake = _FakeOpenAI()
        p = OpenAIEmbeddingProvider(client=fake, dim=4, max_batch=128)
        out = p.embed_batch([f"text-{i}" for i in range(50)])
        assert len(out) == 50
        assert len(fake.calls) == 1
        assert len(fake.calls[0]["input"]) == 50

    def test_chunks_over_max_batch(self) -> None:
        fake = _FakeOpenAI()
        p = OpenAIEmbeddingProvider(client=fake, dim=4, max_batch=10)
        out = p.embed_batch([f"text-{i}" for i in range(25)])
        assert len(out) == 25
        assert len(fake.calls) == 3
        assert [len(c["input"]) for c in fake.calls] == [10, 10, 5]

    def test_empty_returns_empty(self) -> None:
        fake = _FakeOpenAI()
        p = OpenAIEmbeddingProvider(client=fake, dim=4)
        assert p.embed_batch([]) == []
        assert fake.calls == []

    def test_single_text_uses_batch(self) -> None:
        fake = _FakeOpenAI()
        p = OpenAIEmbeddingProvider(client=fake, dim=4)
        v = p.embed("hello")
        assert len(v) == 4
        assert len(fake.calls) == 1


class TestOpenAIRetry:
    def test_retries_then_succeeds_on_429(self) -> None:
        slept: list[float] = []
        fake = _FakeOpenAI(fail_n=2, fail_exc=_FakeRateLimit)
        p = OpenAIEmbeddingProvider(
            client=fake, dim=4,
            retry=_RetryConfig(max_attempts=5, base=0.001, cap=0.01,
                               rng=lambda: 0.5),
            sleep=slept.append,
        )
        out = p.embed_batch(["a", "b"])
        assert len(out) == 2
        assert len(fake.calls) == 3
        assert len(slept) == 2

    def test_non_transient_raises_immediately(self) -> None:
        fake = _FakeOpenAI(fail_n=99, fail_exc=lambda: ValueError("bad input"))
        p = OpenAIEmbeddingProvider(
            client=fake, dim=4,
            retry=_RetryConfig(max_attempts=5, base=0.0, cap=0.0,
                               rng=lambda: 0.0),
            sleep=lambda _: None,
        )
        with pytest.raises(ValueError):
            p.embed_batch(["x"])
        assert len(fake.calls) == 1

    def test_exhausts_retries_then_raises(self) -> None:
        fake = _FakeOpenAI(fail_n=10, fail_exc=_FakeRateLimit)
        p = OpenAIEmbeddingProvider(
            client=fake, dim=4,
            retry=_RetryConfig(max_attempts=3, base=0.0, cap=0.0,
                               rng=lambda: 0.0),
            sleep=lambda _: None,
        )
        with pytest.raises(_FakeRateLimit):
            p.embed_batch(["x"])
        assert len(fake.calls) == 3


class TestOpenAIDimensionsParam:
    def test_passes_dimensions_when_non_native(self) -> None:
        fake = _FakeOpenAI()
        p = OpenAIEmbeddingProvider(client=fake, model="text-embedding-3-small",
                                    dim=512)
        p.embed_batch(["hi"])
        assert fake.calls[0]["dimensions"] == 512

    def test_omits_dimensions_when_native(self) -> None:
        fake = _FakeOpenAI()
        p = OpenAIEmbeddingProvider(client=fake, model="text-embedding-3-small",
                                    dim=1536)  # native
        p.embed_batch(["hi"])
        assert "dimensions" not in fake.calls[0]


class TestOpenAITokenCount:
    def test_uses_tiktoken_when_available(self) -> None:
        fake = _FakeOpenAI()
        p = OpenAIEmbeddingProvider(client=fake, dim=4)
        n = p._count_tokens(["hello world", "another sentence here"])
        assert n > 0


class TestOpenAIAsync:
    def test_async_batch(self) -> None:
        class _AsyncEmb:
            def __init__(self, parent: "_FakeOpenAI") -> None:
                self._p = parent

            async def create(self, *, model: str, input: list[str], **kw: Any) -> _FakeResp:
                self._p.calls.append({"model": model, "input": list(input), **kw})
                return _FakeResp([deterministic_embed(t, dim=4) for t in input])

        class _Async:
            def __init__(self, fake: "_FakeOpenAI") -> None:
                self.embeddings = _AsyncEmb(fake)

        fake = _FakeOpenAI()
        p = OpenAIEmbeddingProvider(
            client=fake, async_client=_Async(fake), dim=4, max_batch=2,
        )

        async def run() -> list[list[float]]:
            return await p.aembed_batch(["a", "b", "c"])

        out = asyncio.run(run())
        assert len(out) == 3
        assert len(fake.calls) == 2  # batched 2 + 1


# ---------------------------------------------------------------------------
# Caching wrapper
# ---------------------------------------------------------------------------

class TestCaching:
    def test_hits_short_circuit_inner(self) -> None:
        fake = _FakeOpenAI()
        inner = OpenAIEmbeddingProvider(client=fake, dim=4)
        cached = CachingEmbeddingProvider(inner)
        cached.embed("hello")
        cached.embed("hello")
        cached.embed("hello")
        assert len(fake.calls) == 1

    def test_partial_hit_only_misses_go_to_inner(self) -> None:
        fake = _FakeOpenAI()
        inner = OpenAIEmbeddingProvider(client=fake, dim=4)
        cached = CachingEmbeddingProvider(inner)
        cached.embed_batch(["a", "b", "c"])
        cached.embed_batch(["a", "b", "d"])  # only "d" should hit API
        # Calls 0 = ["a", "b", "c"]; calls 1 should contain only "d"
        assert fake.calls[1]["input"] == ["d"]

    def test_lru_eviction(self) -> None:
        fake = _FakeOpenAI()
        inner = OpenAIEmbeddingProvider(client=fake, dim=4)
        cached = CachingEmbeddingProvider(inner, max_items=2)
        cached.embed("a")
        cached.embed("b")
        cached.embed("c")  # evicts "a"
        cached.embed("a")  # cache miss → re-fetch
        # Original "a" call + b + c + re-fetched "a" = 4 calls
        assert len(fake.calls) == 4

    def test_disk_cache_persists_across_instances(self, tmp_path: Path) -> None:
        path = tmp_path / "embed.sqlite"
        fake1 = _FakeOpenAI()
        c1 = CachingEmbeddingProvider(
            OpenAIEmbeddingProvider(client=fake1, dim=4),
            disk_path=path,
        )
        c1.embed("persisted text")

        fake2 = _FakeOpenAI()
        c2 = CachingEmbeddingProvider(
            OpenAIEmbeddingProvider(client=fake2, dim=4),
            disk_path=path,
        )
        c2.embed("persisted text")
        assert len(fake2.calls) == 0  # served from disk

    def test_cache_keyed_by_model(self) -> None:
        fake_small = _FakeOpenAI()
        fake_large = _FakeOpenAI()
        c_small = CachingEmbeddingProvider(
            OpenAIEmbeddingProvider(
                client=fake_small, model="text-embedding-3-small", dim=4),
        )
        c_large = CachingEmbeddingProvider(
            OpenAIEmbeddingProvider(
                client=fake_large, model="text-embedding-3-large", dim=4),
        )
        c_small.embed("same text")
        c_large.embed("same text")
        # Different model → different cache key → both inner providers called.
        assert len(fake_small.calls) == 1
        assert len(fake_large.calls) == 1


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class TestFactory:
    def test_no_key_returns_deterministic(self) -> None:
        class _S:
            openai_api_key = None
        p = build_default_provider(settings=_S(), use_cache=False)
        assert isinstance(p, DeterministicEmbeddingProvider)

    def test_with_key_returns_caching_wrapper(self) -> None:
        class _Sec:
            def get_secret_value(self) -> str:
                return "sk-test"

        class _S:
            openai_api_key = _Sec()

        p = build_default_provider(settings=_S(), use_cache=True)
        assert isinstance(p, CachingEmbeddingProvider)

    def test_with_key_no_cache(self) -> None:
        class _Sec:
            def get_secret_value(self) -> str:
                return "sk-test"

        class _S:
            openai_api_key = _Sec()

        p = build_default_provider(settings=_S(), use_cache=False)
        assert isinstance(p, OpenAIEmbeddingProvider)


# ---------------------------------------------------------------------------
# Integration: SemanticStore picks up the provider
# ---------------------------------------------------------------------------

class TestSemanticStoreWithProvider:
    def test_provider_used(self) -> None:
        from codepilot.memory.semantic import SemanticStore

        fake = _FakeOpenAI()
        provider = OpenAIEmbeddingProvider(client=fake, dim=4)
        store = SemanticStore(provider=provider, vector_size=4)
        store.add_lesson(
            repo="r", issue_type="bug_fix", files=[],
            approach="x", outcome="DONE", summary="seeded",
        )
        store.query("seeded", k=1)
        assert len(fake.calls) == 2  # 1 add + 1 query

    def test_passing_both_raises(self) -> None:
        from codepilot.memory.semantic import SemanticStore

        with pytest.raises(ValueError, match="either"):
            SemanticStore(
                provider=DeterministicEmbeddingProvider(),
                embed_fn=deterministic_embed,
            )

    def test_legacy_embed_fn_still_works(self) -> None:
        from codepilot.memory.semantic import SemanticStore

        store = SemanticStore(embed_fn=deterministic_embed)
        store.add_lesson(
            repo="r", issue_type="bug_fix", files=[],
            approach="x", outcome="DONE", summary="seeded",
        )
        hits = store.query("seeded", k=1)
        assert len(hits) == 1
