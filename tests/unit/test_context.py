import asyncio

import pytest

from codepilot.observability.context import (
    bind_span,
    bind_state,
    bind_task,
    context_snapshot,
    current_span_id,
    current_trace_id,
    with_trace,
)


class TestBindTask:
    def test_mints_trace_id(self) -> None:
        with bind_task(42, repo="acme/x") as tid:
            assert current_trace_id() == tid
            snap = context_snapshot()
            assert snap["issue_id"] == 42
            assert snap["repo"] == "acme/x"
            assert snap["trace_id"] == tid
        assert current_trace_id() is None

    def test_explicit_trace_id_pinned(self) -> None:
        with bind_task(1, trace_id="abc123") as tid:
            assert tid == "abc123"


class TestBindSpan:
    def test_parent_child_chain(self) -> None:
        with bind_task(1):
            with bind_span("outer") as outer_sid:
                assert current_span_id() == outer_sid
                with bind_span("inner") as inner_sid:
                    snap = context_snapshot()
                    assert snap["span_id"] == inner_sid
                    assert snap["parent_span_id"] == outer_sid
                    assert inner_sid != outer_sid
                assert current_span_id() == outer_sid

    def test_trace_inherited_into_span(self) -> None:
        with bind_task(7) as tid:
            with bind_span("foo"):
                assert current_trace_id() == tid


class TestBindState:
    def test_state_set_and_reset(self) -> None:
        with bind_task(1):
            with bind_state("EXPLORING"):
                assert context_snapshot()["state"] == "EXPLORING"
            assert "state" not in context_snapshot()


class TestDecorator:
    def test_sync_with_trace(self) -> None:
        captured: dict[str, str | None] = {}

        @with_trace("fn", agent="coder")
        def fn() -> None:
            captured["sid"] = current_span_id()

        with bind_task(1):
            fn()

        assert captured["sid"] is not None

    def test_async_with_trace(self) -> None:
        captured: dict[str, str | None] = {}

        @with_trace("afn", agent="explorer")
        async def afn() -> None:
            captured["sid"] = current_span_id()

        with bind_task(2):
            asyncio.run(afn())

        assert captured["sid"] is not None


class TestAsyncPropagation:
    def test_contextvar_inherits_into_subtask(self) -> None:
        async def child() -> str | None:
            return current_trace_id()

        async def parent() -> str | None:
            return await asyncio.create_task(child())

        with bind_task(99) as tid:
            got = asyncio.run(parent())
            assert got == tid


class TestSnapshot:
    def test_only_set_keys(self) -> None:
        snap = context_snapshot()
        assert snap == {}
        with bind_task(5):
            keys = set(context_snapshot())
            assert "trace_id" in keys
            assert "issue_id" in keys
