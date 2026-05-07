"""Semantic store integration. Uses Qdrant `:memory:` mode — no external service."""
import pytest

from codepilot.memory.embeddings import deterministic_embed
from codepilot.memory.semantic import Lesson, SemanticStore


@pytest.fixture
def store() -> SemanticStore:
    return SemanticStore(embed_fn=deterministic_embed)


def _seed(store: SemanticStore) -> None:
    store.add_lesson(
        repo="acme/x", issue_type="bug_fix",
        files=["src/a.py"], approach="add null check",
        outcome="DONE", summary="Null pointer in user lookup",
    )
    store.add_lesson(
        repo="acme/x", issue_type="bug_fix",
        files=["src/auth.py"], approach="fix off-by-one in token expiry",
        outcome="DONE", summary="Token expiry check used < instead of <=",
    )
    store.add_lesson(
        repo="acme/y", issue_type="dependency_update",
        files=["pyproject.toml"], approach="bump pydantic v1 → v2",
        outcome="DONE", summary="Pydantic v2 migration broke field validators",
    )
    store.add_lesson(
        repo="acme/y", issue_type="documentation",
        files=["README.md"], approach="rewrite quickstart",
        outcome="DONE", summary="README was stale after v2 release",
    )


class TestCollectionLifecycle:
    def test_collection_created(self, store: SemanticStore) -> None:
        names = {c.name for c in store.client.get_collections().collections}
        assert store.collection in names

    def test_count_starts_zero(self, store: SemanticStore) -> None:
        assert store.count() == 0


class TestAddAndQuery:
    def test_returns_top_k(self, store: SemanticStore) -> None:
        _seed(store)
        hits = store.query("Pydantic upgrade fails", k=2)
        assert len(hits) == 2
        assert all(isinstance(h.lesson, Lesson) for h in hits)

    def test_score_descending(self, store: SemanticStore) -> None:
        _seed(store)
        hits = store.query("any query", k=4)
        scores = [h.score for h in hits]
        assert scores == sorted(scores, reverse=True)

    def test_repo_filter_isolates(self, store: SemanticStore) -> None:
        _seed(store)
        hits = store.query("anything", k=10, repo="acme/x")
        repos = {h.lesson.repo for h in hits}
        assert repos == {"acme/x"}
        assert len(hits) == 2

    def test_issue_type_filter(self, store: SemanticStore) -> None:
        _seed(store)
        hits = store.query("anything", k=10, issue_type="bug_fix")
        types = {h.lesson.issue_type for h in hits}
        assert types == {"bug_fix"}

    def test_combined_filters(self, store: SemanticStore) -> None:
        _seed(store)
        hits = store.query("any", k=10, repo="acme/y", issue_type="documentation")
        assert len(hits) == 1
        assert hits[0].lesson.summary.startswith("README")


class TestSimilarityShape:
    def test_matching_summary_outranks_unrelated(self, store: SemanticStore) -> None:
        store.add_lesson(
            repo="r", issue_type="bug_fix", files=[],
            approach="match",
            outcome="DONE", summary="pydantic v2 migration off-by-one",
        )
        store.add_lesson(
            repo="r", issue_type="documentation", files=[],
            approach="rewrite",
            outcome="DONE", summary="completely unrelated readme tweak",
        )
        hits = store.query("pydantic v2 migration off-by-one", k=2)
        assert hits[0].lesson.summary.startswith("pydantic v2")


class TestPersistencePerInstance:
    def test_count_after_add(self, store: SemanticStore) -> None:
        _seed(store)
        assert store.count() == 4


class TestCustomLessonId:
    def test_custom_id_used(self, store: SemanticStore) -> None:
        lesson = store.add_lesson(
            repo="r", issue_type="bug_fix", files=[],
            approach="a", outcome="DONE", summary="s",
            lesson_id="00000000-0000-0000-0000-000000000001",
        )
        assert lesson.id == "00000000-0000-0000-0000-000000000001"
