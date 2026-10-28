"""OpenTelemetry tracing for the agent.

Spans follow the OpenTelemetry GenAI conventions: invoke_agent for a whole question, chat for
each model call and execute_tool for each tool call. Prompts and passages are not recorded,
only the model, token counts, search queries, the titles found and the final answer.

Until configure() is called, OpenTelemetry's default no-op tracer is used and tracing costs
nothing.
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

tracer = trace.get_tracer("signalfloor_agent")


def configure(endpoint: str, *, service_name: str = "signalfloor-agent") -> TracerProvider:
    """Send spans to an OTLP/HTTP endpoint, such as http://localhost:8000/v1/traces.

    Call shutdown() on the returned provider before exiting, or the last spans are lost.
    """
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    return provider


def current_trace_id() -> str | None:
    """The current trace id as 32 hex characters, or None when tracing is off."""
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else None
