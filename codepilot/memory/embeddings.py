"""Production-grade embedding layer.

Design goals:
  * Protocol-based — swap providers without touching call sites.
  * Batching — one API round trip per N texts (huge cost win).
  * Retries — exponential backoff on transient errors.
  * Caching — in-process LRU + optional sqlite-backed disk cache (text → vector).
  * Cost telemetry — every batch logs `embed.batch` with tokens + USD estimate.
  * Async — `aembed` / `aembed_batch` for use inside the orchestrator's loop.
  * Test-friendly — `DeterministicEmbeddingProvider` satisfies the same Protocol.

Backward-compat: legacy `EmbedFn` and `deterministic_embed` callable retained.
`SemanticStore` accepts either an `EmbeddingProvider` or an old `EmbedFn`.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import random
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final, Protocol, runtime_checkable

from codepilot.observability import get_logger

_log = get_logger("memory.embeddings")

EmbedFn = Callable[[str], list[float]]

DEFAULT_DIM: Final[int] = 128
"""Test/deterministic dim. Production uses provider's native dim (1536 for OpenAI 3-small)."""


# ---------------------------------------------------------------------------
# Cost table — keep in sync with provider pricing.
# Source: https://openai.com/api/pricing/  (text-embedding-3-* family)
# ---------------------------------------------------------------------------
_OPENAI_USD_PER_1K_TOKENS: dict[str, float] = {
    "text-embedding-3-small": 0.00002,
    "text-embedding-3-large": 0.00013,
    "text-embedding-ada-002": 0.00010,
}

_OPENAI_NATIVE_DIMS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


# ---------------------------------------------------------------------------
# Provider protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def dim(self) -> int: ...

    def embed(self, text: str) -> list[float]: ...

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def aembed(self, text: str) -> list[float]: ...

    async def aembed_batch(self, texts: Sequence[str]) -> list[list[float]]: ...


class _BaseProvider:
    """Default async = run sync in a thread; default single = batch of 1."""

    def embed(self, text: str) -> list[float]:  # pragma: no cover - overridden
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:  # pragma: no cover
        return [self.embed(t) for t in texts]

    async def aembed(self, text: str) -> list[float]:
        return await asyncio.to_thread(self.embed, text)

    async def aembed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        return await asyncio.to_thread(self.embed_batch, list(texts))


# ---------------------------------------------------------------------------
# Deterministic provider (tests, dev offline)
# ---------------------------------------------------------------------------

class DeterministicEmbeddingProvider(_BaseProvider):
    """SHA-256 derived. Stable, no network, no model. Tests + offline dev."""

    def __init__(self, *, dim: int = DEFAULT_DIM) -> None:
        self._dim = dim

    @property
    def model_name(self) -> str:
        return "deterministic-sha256"

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> list[float]:
        return deterministic_embed(text, self._dim)

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


def deterministic_embed(text: str, dim: int = DEFAULT_DIM) -> list[float]:
    """Legacy callable. Stable for tests; same text → same unit vector."""
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    raw: list[float] = []
    while len(raw) < dim:
        for b in seed:
            raw.append((b / 255.0) * 2.0 - 1.0)
            if len(raw) >= dim:
                break
        seed = hashlib.sha256(seed).digest()
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [x / norm for x in raw]


# ---------------------------------------------------------------------------
# OpenAI provider — production
# ---------------------------------------------------------------------------

class _RetryConfig:
    __slots__ = ("max_attempts", "base", "cap", "rng")

    def __init__(self, *, max_attempts: int = 5, base: float = 0.5,
                 cap: float = 30.0, rng: Callable[[], float] | None = None) -> None:
        self.max_attempts = max_attempts
        self.base = base
        self.cap = cap
        self.rng = rng or random.random

    def backoff(self, attempt: int) -> float:
        return min(self.cap, self.base * (2 ** (attempt - 1))) * (0.5 + self.rng())


_TRANSIENT_OPENAI_TYPES: tuple[str, ...] = (
    "RateLimitError", "APITimeoutError", "APIConnectionError",
    "InternalServerError", "ServiceUnavailableError",
)


def _is_transient(exc: BaseException) -> bool:
    name = type(exc).__name__
    if name in _TRANSIENT_OPENAI_TYPES:
        return True
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and (status == 429 or 500 <= status < 600):
        return True
    return False


class OpenAIEmbeddingProvider(_BaseProvider):
    """Production OpenAI embeddings.

    - Batches up to `max_batch` texts per request.
    - Retries transient errors with full-jitter exponential backoff.
    - Counts input tokens via tiktoken; logs latency + USD estimate per batch.
    - Async path uses `AsyncOpenAI` directly (no thread offload).

    Either pass `client` / `async_client` (for tests / DI) or supply `api_key`
    so the provider builds them lazily.
    """

    def __init__(
        self,
        *,
        model: str = "text-embedding-3-small",
        dim: int | None = None,
        api_key: str | None = None,
        client: Any | None = None,
        async_client: Any | None = None,
        max_batch: int = 128,
        retry: _RetryConfig | None = None,
        encoding_name: str = "cl100k_base",
        sleep: Callable[[float], None] | None = None,
        usd_per_1k: float | None = None,
    ) -> None:
        self._model = model
        self._dim = dim or _OPENAI_NATIVE_DIMS.get(model, 1536)
        self._api_key = api_key
        self._client = client
        self._async_client = async_client
        self._max_batch = max_batch
        self._retry = retry or _RetryConfig()
        self._sleep = sleep or time.sleep
        self._encoding_name = encoding_name
        self._usd_per_1k = (
            usd_per_1k if usd_per_1k is not None
            else _OPENAI_USD_PER_1K_TOKENS.get(model, 0.0)
        )
        self._encoding: Any | None = None

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dim(self) -> int:
        return self._dim

    # -- client lazy build ----------------------------------------------

    def _get_client(self) -> Any:
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self._api_key) if self._api_key else OpenAI()
        return self._client

    def _get_async_client(self) -> Any:
        if self._async_client is None:
            from openai import AsyncOpenAI
            self._async_client = (
                AsyncOpenAI(api_key=self._api_key) if self._api_key else AsyncOpenAI()
            )
        return self._async_client

    def _get_encoding(self) -> Any:
        if self._encoding is None:
            try:
                import tiktoken
                self._encoding = tiktoken.get_encoding(self._encoding_name)
            except Exception:
                self._encoding = "missing"
        return self._encoding

    def _count_tokens(self, texts: Sequence[str]) -> int:
        enc = self._get_encoding()
        if enc == "missing":
            return sum(max(1, len(t) // 4) for t in texts)
        return sum(len(enc.encode(t)) for t in texts)

    def _build_kwargs(self, texts: Sequence[str]) -> dict[str, Any]:
        kw: dict[str, Any] = {"model": self._model, "input": list(texts)}
        if self._dim and self._dim != _OPENAI_NATIVE_DIMS.get(self._model):
            kw["dimensions"] = self._dim
        return kw

    # -- sync ------------------------------------------------------------

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        for chunk in _chunked(texts, self._max_batch):
            out.extend(self._call_batch_sync(chunk))
        return out

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def _call_batch_sync(self, chunk: list[str]) -> list[list[float]]:
        last_exc: BaseException | None = None
        for attempt in range(1, self._retry.max_attempts + 1):
            t0 = time.monotonic()
            try:
                resp = self._get_client().embeddings.create(**self._build_kwargs(chunk))
                latency_ms = int((time.monotonic() - t0) * 1000)
                self._log_batch(chunk, latency_ms, attempt)
                return [list(d.embedding) for d in resp.data]
            except BaseException as exc:
                last_exc = exc
                if attempt >= self._retry.max_attempts or not _is_transient(exc):
                    raise
                wait = self._retry.backoff(attempt)
                _log.warning(
                    "embed.retry",
                    error=type(exc).__name__, attempt=attempt, sleep_s=round(wait, 3),
                )
                self._sleep(wait)
        if last_exc is not None:  # pragma: no cover - defensive
            raise last_exc
        raise RuntimeError("unreachable")

    # -- async -----------------------------------------------------------

    async def aembed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        for chunk in _chunked(texts, self._max_batch):
            out.extend(await self._call_batch_async(chunk))
        return out

    async def aembed(self, text: str) -> list[float]:
        return (await self.aembed_batch([text]))[0]

    async def _call_batch_async(self, chunk: list[str]) -> list[list[float]]:
        for attempt in range(1, self._retry.max_attempts + 1):
            t0 = time.monotonic()
            try:
                resp = await self._get_async_client().embeddings.create(
                    **self._build_kwargs(chunk),
                )
                latency_ms = int((time.monotonic() - t0) * 1000)
                self._log_batch(chunk, latency_ms, attempt)
                return [list(d.embedding) for d in resp.data]
            except BaseException as exc:
                if attempt >= self._retry.max_attempts or not _is_transient(exc):
                    raise
                wait = self._retry.backoff(attempt)
                _log.warning(
                    "embed.retry",
                    error=type(exc).__name__, attempt=attempt, sleep_s=round(wait, 3),
                )
                await asyncio.sleep(wait)
        raise RuntimeError("unreachable")  # pragma: no cover

    # -- telemetry -------------------------------------------------------

    def _log_batch(self, chunk: list[str], latency_ms: int, attempts: int) -> None:
        tokens = self._count_tokens(chunk)
        usd = (tokens / 1000.0) * self._usd_per_1k
        _log.info(
            "embed.batch",
            model=self._model, count=len(chunk), tokens=tokens,
            usd=round(usd, 6), latency_ms=latency_ms, attempts=attempts,
        )


def _chunked(seq: Sequence[str], size: int) -> list[list[str]]:
    return [list(seq[i:i + size]) for i in range(0, len(seq), size)]


# ---------------------------------------------------------------------------
# Caching wrapper — wraps any provider; in-memory LRU + optional sqlite disk
# ---------------------------------------------------------------------------

class CachingEmbeddingProvider(_BaseProvider):
    """Thread-safe LRU + optional sqlite persistent cache.

    Cache key = sha256(model_name + ':' + text). Misses go to the inner provider
    in one batched call; hits short-circuit. Logs `embed.cache` hits/misses.
    """

    def __init__(
        self,
        inner: EmbeddingProvider,
        *,
        max_items: int = 10_000,
        disk_path: str | Path | None = None,
    ) -> None:
        self._inner = inner
        self._max = max_items
        self._mem: "OrderedDict[str, list[float]]" = OrderedDict()
        self._lock = threading.Lock()
        self._disk = _DiskKV(Path(disk_path)) if disk_path else None

    @property
    def model_name(self) -> str:
        return self._inner.model_name

    @property
    def dim(self) -> int:
        return self._inner.dim

    def _key(self, text: str) -> str:
        h = hashlib.sha256()
        h.update(self.model_name.encode("utf-8"))
        h.update(b":")
        h.update(text.encode("utf-8"))
        return h.hexdigest()

    def _get_cached(self, key: str) -> list[float] | None:
        with self._lock:
            if key in self._mem:
                self._mem.move_to_end(key)
                return list(self._mem[key])
        if self._disk is not None:
            v = self._disk.get(key)
            if v is not None:
                self._set_mem(key, v)
                return list(v)
        return None

    def _set_mem(self, key: str, vec: list[float]) -> None:
        with self._lock:
            self._mem[key] = vec
            self._mem.move_to_end(key)
            while len(self._mem) > self._max:
                self._mem.popitem(last=False)

    def _set_both(self, key: str, vec: list[float]) -> None:
        self._set_mem(key, vec)
        if self._disk is not None:
            self._disk.put(key, vec)

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float] | None] = [None] * len(texts)
        misses_idx: list[int] = []
        misses_text: list[str] = []
        misses_key: list[str] = []
        for i, t in enumerate(texts):
            key = self._key(t)
            v = self._get_cached(key)
            if v is None:
                misses_idx.append(i)
                misses_text.append(t)
                misses_key.append(key)
            else:
                out[i] = v
        if misses_text:
            fresh = self._inner.embed_batch(misses_text)
            for i, key, vec in zip(misses_idx, misses_key, fresh, strict=True):
                self._set_both(key, vec)
                out[i] = vec
        _log.debug(
            "embed.cache",
            hits=len(texts) - len(misses_text), misses=len(misses_text),
            total=len(texts),
        )
        return [v for v in out if v is not None]  # all populated

    async def aembed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float] | None] = [None] * len(texts)
        misses_idx: list[int] = []
        misses_text: list[str] = []
        misses_key: list[str] = []
        for i, t in enumerate(texts):
            key = self._key(t)
            v = self._get_cached(key)
            if v is None:
                misses_idx.append(i)
                misses_text.append(t)
                misses_key.append(key)
            else:
                out[i] = v
        if misses_text:
            fresh = await self._inner.aembed_batch(misses_text)
            for i, key, vec in zip(misses_idx, misses_key, fresh, strict=True):
                self._set_both(key, vec)
                out[i] = vec
        return [v for v in out if v is not None]


class _DiskKV:
    """Tiny sqlite-backed key→json blob store. Single-writer, multi-reader safe."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._lock = threading.Lock()
        with self._connect() as cx:
            cx.execute("CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v BLOB)")
            cx.commit()

    def _connect(self) -> sqlite3.Connection:
        cx = sqlite3.connect(str(self._path), timeout=5.0,
                             check_same_thread=False, isolation_level=None)
        cx.execute("PRAGMA journal_mode=WAL")
        return cx

    def get(self, key: str) -> list[float] | None:
        with self._lock, self._connect() as cx:
            row = cx.execute("SELECT v FROM kv WHERE k = ?", (key,)).fetchone()
        if row is None:
            return None
        return list(json.loads(row[0]))

    def put(self, key: str, vec: list[float]) -> None:
        blob = json.dumps(vec)
        with self._lock, self._connect() as cx:
            cx.execute("INSERT OR REPLACE INTO kv(k, v) VALUES(?, ?)", (key, blob))


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_default_provider(
    *,
    settings: Any | None = None,
    use_cache: bool = True,
    disk_cache_path: str | Path | None = None,
) -> EmbeddingProvider:
    """Wire production provider from settings.

    Falls back to `DeterministicEmbeddingProvider` when no LLM key is present
    (lets `doctor` smoke-tests run offline).
    """
    if settings is None:
        from codepilot.config import get_settings
        settings = get_settings()

    api_key_secret = getattr(settings, "openai_api_key", None)
    if api_key_secret is None:
        _log.warning("embed.fallback.deterministic", reason="no openai_api_key")
        return DeterministicEmbeddingProvider()

    inner: EmbeddingProvider = OpenAIEmbeddingProvider(
        api_key=api_key_secret.get_secret_value() if api_key_secret else None,
    )
    if use_cache:
        return CachingEmbeddingProvider(inner, disk_path=disk_cache_path)
    return inner


# ---------------------------------------------------------------------------
# Legacy compat — old `make_openai_embed` returns an `EmbedFn`
# ---------------------------------------------------------------------------

def make_openai_embed(model: str = "text-embedding-3-small") -> EmbedFn:
    """Deprecated. Returns single-text callable backed by `OpenAIEmbeddingProvider`."""
    p = OpenAIEmbeddingProvider(model=model)

    def _embed(text: str) -> list[float]:
        return p.embed(text)

    return _embed
