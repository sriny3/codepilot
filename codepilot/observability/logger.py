"""structlog setup — JSON to file, console pretty in dev. Auto-binds trace context."""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import Any

import structlog

from codepilot.observability.context import context_snapshot
from codepilot.observability.redaction import structlog_redactor


def _ctx_processor(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Inject current trace/span/issue/agent into every log line."""
    snap = context_snapshot()
    for k, v in snap.items():
        event_dict.setdefault(k, v)
    return event_dict


_CONFIGURED = False


def configure(
    *,
    level: str = "INFO",
    log_dir: Path | str | None = None,
    log_format: str = "json",
    file_name: str = "codepilot.jsonl",
) -> None:
    """Idempotent. Safe to call from tests with different settings."""
    global _CONFIGURED

    log_level = getattr(logging, level.upper(), logging.INFO)

    handlers: list[logging.Handler] = []
    if log_dir is not None:
        d = Path(log_dir)
        d.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.TimedRotatingFileHandler(
            d / file_name, when="midnight", backupCount=30, encoding="utf-8", utc=True,
        )
        fh.setFormatter(logging.Formatter("%(message)s"))
        handlers.append(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(message)s"))
    handlers.append(sh)

    root = logging.getLogger()
    root.handlers.clear()
    for h in handlers:
        root.addHandler(h)
    root.setLevel(log_level)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _ctx_processor,
        structlog_redactor,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if log_format == "console":
        renderer: Any = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer(sort_keys=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
    _CONFIGURED = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    if not _CONFIGURED:
        configure()
    return structlog.get_logger(name)


def reset_for_tests() -> None:
    global _CONFIGURED
    _CONFIGURED = False
    structlog.reset_defaults()
    logging.getLogger().handlers.clear()
