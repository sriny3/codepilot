import pytest
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from codepilot.observability import tracing
from codepilot.observability.context import bind_task


@pytest.fixture
def memory_exporter() -> InMemorySpanExporter:
    """Force a fresh provider with in-memory exporter — bypasses set-once guard."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    otel_trace._TRACER_PROVIDER = provider  # type: ignore[attr-defined]
    yield exporter
    tracing.reset_for_tests()


class TestSpanCreation:
    def test_start_span_yields_span(self, memory_exporter: InMemorySpanExporter) -> None:
        with tracing.start_span("step", retry=1) as span:
            assert span is not None

    def test_span_attrs_include_context(self, memory_exporter: InMemorySpanExporter) -> None:
        with bind_task(42, repo="acme/x"):
            with tracing.start_span("step"):
                pass
        spans = memory_exporter.get_finished_spans()
        assert spans, "no span finished"
        attrs = dict(spans[-1].attributes or {})
        assert "codepilot.trace_id" in attrs
        assert attrs.get("codepilot.issue_id") == "42"
        assert attrs.get("codepilot.repo") == "acme/x"

    def test_extra_attrs_recorded(self, memory_exporter: InMemorySpanExporter) -> None:
        with tracing.start_span("step", retry=1, agent="coder"):
            pass
        spans = memory_exporter.get_finished_spans()
        attrs = dict(spans[-1].attributes or {})
        assert attrs.get("retry") == 1
        assert attrs.get("agent") == "coder"


class TestNoOpWithoutEndpoint:
    def test_no_endpoint_does_not_raise(self) -> None:
        tracing.reset_for_tests()
        tracing.configure_tracing(service_name="test", otlp_endpoint=None)
        with tracing.start_span("noop"):
            pass
        tracing.reset_for_tests()
