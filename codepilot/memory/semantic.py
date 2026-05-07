"""Semantic memory: durable lessons learned, queried before each new task.

Backed by Qdrant. Tests use `:memory:` mode — no external service.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from codepilot.memory.embeddings import (
    DEFAULT_DIM,
    DeterministicEmbeddingProvider,
    EmbedFn,
    EmbeddingProvider,
)

DEFAULT_COLLECTION = "lessons"


class Lesson(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    repo: str
    issue_type: str
    files: list[str] = Field(default_factory=list)
    approach: str
    outcome: str
    summary: str
    created_at: datetime


class LessonHit(BaseModel):
    lesson: Lesson
    score: float


class SemanticStore:
    def __init__(
        self,
        *,
        client: QdrantClient | None = None,
        collection: str = DEFAULT_COLLECTION,
        provider: EmbeddingProvider | None = None,
        embed_fn: EmbedFn | None = None,
        vector_size: int | None = None,
    ) -> None:
        self._client = client or QdrantClient(":memory:")
        self._collection = collection

        if provider is not None and embed_fn is not None:
            raise ValueError("pass either `provider` or `embed_fn`, not both")

        self._provider: EmbeddingProvider
        if provider is not None:
            self._provider = provider
        elif embed_fn is not None:
            self._provider = _FnProviderShim(embed_fn, dim=vector_size or DEFAULT_DIM)
        else:
            self._provider = DeterministicEmbeddingProvider(
                dim=vector_size or DEFAULT_DIM,
            )

        self._vector_size = vector_size or self._provider.dim
        self._ensure_collection()

    @property
    def client(self) -> QdrantClient:
        return self._client

    @property
    def collection(self) -> str:
        return self._collection

    def _ensure_collection(self) -> None:
        existing = {c.name for c in self._client.get_collections().collections}
        if self._collection in existing:
            return
        self._client.create_collection(
            collection_name=self._collection,
            vectors_config=VectorParams(
                size=self._vector_size, distance=Distance.COSINE,
            ),
        )

    # ---- writes --------------------------------------------------------

    def add_lesson(
        self,
        *,
        repo: str,
        issue_type: str,
        files: list[str],
        approach: str,
        outcome: str,
        summary: str,
        lesson_id: str | None = None,
    ) -> Lesson:
        lesson_id = lesson_id or uuid.uuid4().hex
        lesson = Lesson(
            id=lesson_id, repo=repo, issue_type=issue_type, files=files,
            approach=approach, outcome=outcome, summary=summary,
            created_at=datetime.now(timezone.utc),
        )
        vec = self._provider.embed(_embed_text(lesson))
        self._client.upsert(
            collection_name=self._collection,
            points=[
                PointStruct(
                    id=lesson_id,
                    vector=vec,
                    payload=lesson.model_dump(mode="json"),
                )
            ],
        )
        return lesson

    # ---- reads ---------------------------------------------------------

    def query(
        self,
        task_desc: str,
        *,
        k: int = 3,
        repo: str | None = None,
        issue_type: str | None = None,
    ) -> list[LessonHit]:
        flt = self._build_filter(repo=repo, issue_type=issue_type)
        resp = self._client.query_points(
            collection_name=self._collection,
            query=self._provider.embed(task_desc),
            query_filter=flt,
            limit=k,
            with_payload=True,
        )
        out: list[LessonHit] = []
        for r in resp.points:
            lesson = Lesson.model_validate(r.payload)
            out.append(LessonHit(lesson=lesson, score=r.score))
        return out

    def _build_filter(
        self, *, repo: str | None, issue_type: str | None,
    ) -> Filter | None:
        conds: list[FieldCondition] = []
        if repo:
            conds.append(FieldCondition(key="repo", match=MatchValue(value=repo)))
        if issue_type:
            conds.append(
                FieldCondition(key="issue_type", match=MatchValue(value=issue_type))
            )
        if not conds:
            return None
        return Filter(must=conds)

    # ---- maintenance ---------------------------------------------------

    def count(self) -> int:
        return int(self._client.count(self._collection, exact=True).count)

    def delete_collection(self) -> None:
        self._client.delete_collection(self._collection)


class _FnProviderShim:
    """Adapter exposing a legacy `EmbedFn` as an `EmbeddingProvider`."""

    def __init__(self, fn: EmbedFn, *, dim: int) -> None:
        self._fn = fn
        self._dim = dim

    @property
    def model_name(self) -> str:
        return "legacy-embed-fn"

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> list[float]:
        return list(self._fn(text))

    def embed_batch(self, texts: Any) -> list[list[float]]:
        return [self.embed(t) for t in texts]

    async def aembed(self, text: str) -> list[float]:
        import asyncio
        return await asyncio.to_thread(self.embed, text)

    async def aembed_batch(self, texts: Any) -> list[list[float]]:
        import asyncio
        return await asyncio.to_thread(self.embed_batch, list(texts))


def _embed_text(lesson: Lesson) -> str:
    """Compose the text we embed. Keep this concentrated on what's queryable."""
    parts = [
        lesson.summary,
        f"issue_type:{lesson.issue_type}",
        f"approach:{lesson.approach}",
    ]
    if lesson.files:
        parts.append("files:" + ",".join(lesson.files))
    return " | ".join(parts)
