import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from signalfloor_agent.testing import HashingEmbedder


@pytest.fixture
def embedder() -> HashingEmbedder:
    return HashingEmbedder()


@pytest.fixture(scope="session")
def span_exporter() -> InMemorySpanExporter:
    # OpenTelemetry allows one global tracer provider per process, so it is set once here.
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return exporter


@pytest.fixture
def spans(span_exporter: InMemorySpanExporter) -> InMemorySpanExporter:
    span_exporter.clear()
    return span_exporter
