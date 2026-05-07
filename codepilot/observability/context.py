"""Contextvars-based correlation IDs propagated across sync + async + subagent calls."""
from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from functools import wraps
from typing import Any, TypeVar

_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
_span_id: ContextVar[str | None] = ContextVar("span_id", default=None)
_parent_span_id: ContextVar[str | None] = ContextVar("parent_span_id", default=None)
_issue_id: ContextVar[int | None] = ContextVar("issue_id", default=None)
_repo: ContextVar[str | None] = ContextVar("repo", default=None)
_agent_name: ContextVar[str | None] = ContextVar("agent_name", default=None)
_state: ContextVar[str | None] = ContextVar("state", default=None)


def _new_id() -> str:
    return uuid.uuid4().hex


def current_trace_id() -> str | None:
    return _trace_id.get()


def current_span_id() -> str | None:
    return _span_id.get()


def current_issue_id() -> int | None:
    return _issue_id.get()


def current_agent() -> str | None:
    return _agent_name.get()


def current_repo() -> str | None:
    return _repo.get()


def current_state() -> str | None:
    return _state.get()


def context_snapshot() -> dict[str, Any]:
    """Plain dict of every set field — for log binding and span attrs."""
    return {
        k: v
        for k, v in {
            "trace_id": _trace_id.get(),
            "span_id": _span_id.get(),
            "parent_span_id": _parent_span_id.get(),
            "issue_id": _issue_id.get(),
            "repo": _repo.get(),
            "agent": _agent_name.get(),
            "state": _state.get(),
        }.items()
        if v is not None
    }


@contextmanager
def bind_task(issue_id: int, repo: str | None = None,
              trace_id: str | None = None) -> Iterator[str]:
    """Mint a new trace_id pinned to an issue. Use at the moment of issue pickup."""
    tid = trace_id or _new_id()
    tokens: list[Token[Any]] = [
        _trace_id.set(tid),
        _issue_id.set(issue_id),
    ]
    if repo is not None:
        tokens.append(_repo.set(repo))
    try:
        yield tid
    finally:
        for tok in reversed(tokens):
            tok.var.reset(tok)


@contextmanager
def bind_span(name: str, agent: str | None = None) -> Iterator[str]:
    """Open a new span; inherits trace_id, sets parent_span_id to the previous span."""
    parent = _span_id.get()
    sid = _new_id()
    tokens: list[Token[Any]] = [
        _span_id.set(sid),
        _parent_span_id.set(parent),
    ]
    if agent is not None:
        tokens.append(_agent_name.set(agent))
    try:
        yield sid
    finally:
        for tok in reversed(tokens):
            tok.var.reset(tok)
    _ = name  # name is used by the OTel layer; here it just documents intent.


@contextmanager
def bind_state(state: str) -> Iterator[None]:
    tok = _state.set(state)
    try:
        yield
    finally:
        _state.reset(tok)


F = TypeVar("F", bound=Callable[..., Any])


def with_trace(name: str, agent: str | None = None) -> Callable[[F], F]:
    """Decorator: wrap callable in a span. Works on sync and async."""
    import asyncio

    def deco(fn: F) -> F:
        if asyncio.iscoroutinefunction(fn):
            @wraps(fn)
            async def aw(*args: Any, **kw: Any) -> Any:
                with bind_span(name, agent=agent):
                    return await fn(*args, **kw)
            return aw  # type: ignore[return-value]

        @wraps(fn)
        def w(*args: Any, **kw: Any) -> Any:
            with bind_span(name, agent=agent):
                return fn(*args, **kw)
        return w  # type: ignore[return-value]

    return deco
