"""OpenTelemetry tracer wrapper. OTLP optional — no-op when endpoint absent."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

from codepilot.observability.context import context_snapshot

_PROVIDER: TracerProvider | None = None


def configure_tracing(
    *,
    service_name: str = "codepilot",
    otlp_endpoint: str | None = None,
    console_export: bool = False,
) -> None:
    global _PROVIDER
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
        except ImportError:
            pass

    if console_export:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _PROVIDER = provider


def get_tracer(name: str = "codepilot") -> Any:
    return trace.get_tracer(name)


@contextmanager
def start_span(name: str, **attrs: Any) -> Iterator[Any]:
    """Wrap a code block in a span pre-populated with current context."""
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        for k, v in context_snapshot().items():
            span.set_attribute(f"codepilot.{k}", str(v))
        for k, v in attrs.items():
            span.set_attribute(k, v if isinstance(v, (str, int, float, bool)) else str(v))
        yield span


def reset_for_tests() -> None:
    global _PROVIDER
    _PROVIDER = None
    trace._TRACER_PROVIDER = None  # type: ignore[attr-defined]
