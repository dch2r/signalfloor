import socket

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from signalfloor_agent.testing import HashingEmbedder


class NetworkAccess(Exception):
    """Raised when a unit test tries to open a connection. Not an OSError, so nothing that
    handles a server being down can swallow it."""


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail at once on any real connection. Tests stub the model server or use a mock
    transport, so a connection attempt means a test depends on the machine it runs on."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise NetworkAccess(f"unit test tried to reach the network: {args[-1]!r}")

    # Name lookups count: they happen before any connect, and a failed one looks to httpx
    # like a server that is down, which the code handles quietly.
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)


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
