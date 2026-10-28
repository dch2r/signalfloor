"""Receive OpenTelemetry traces over OTLP/HTTP and serve them back.

Any OpenTelemetry SDK can send here: point its OTLP/HTTP exporter at
http://<server>/v1/traces. Both protobuf and JSON bodies are accepted, gzipped or not.

Exporters retry when a request fails, so the same span can arrive twice. Spans are keyed by
trace and span id and duplicates are dropped.
"""

from __future__ import annotations

import base64
import json
import math
import zlib
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from google.protobuf import json_format
from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from signalfloor_server.db import Session
from signalfloor_server.models import Span
from signalfloor_server.schemas import SpanOut

# Far above a normal batch of 512 spans. Applies to the body after gzip is undone, so a small
# compressed body can't expand into gigabytes.
MAX_BODY_BYTES = 10_000_000

PROTOBUF = "application/x-protobuf"
JSON = "application/json"
STATUS = {0: "unset", 1: "ok", 2: "error"}
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

router = APIRouter(tags=["traces"])


@router.post("/v1/traces")
async def ingest(request: Request, session: Session) -> Response:
    """The OTLP/HTTP trace endpoint."""
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in (PROTOBUF, JSON):
        raise HTTPException(415, f"content type must be {PROTOBUF} or {JSON}")
    body = await _read_body(request)
    try:
        export = _parse_json(body) if content_type == JSON else _parse_protobuf(body)
    except (ValueError, TypeError, AttributeError, DecodeError, json_format.ParseError) as e:
        raise HTTPException(400, f"not a valid OTLP trace export: {e}") from e

    rows, rejected = _rows(export)
    if rows:
        await session.execute(insert(Span).on_conflict_do_nothing(), rows)
        await session.commit()

    response = ExportTraceServiceResponse()
    if rejected:
        response.partial_success.rejected_spans = rejected
        response.partial_success.error_message = "spans need a 16 byte trace id and 8 byte span id"
    if content_type == JSON:
        return Response(json_format.MessageToJson(response), media_type=JSON)
    return Response(response.SerializeToString(), media_type=PROTOBUF)


@router.get("/traces/{trace_id}")
async def get_trace(trace_id: str, session: Session) -> list[SpanOut]:
    """Every span in a trace, in the order they started."""
    spans = await load_spans(session, trace_id.lower())
    if not spans:
        raise HTTPException(404, f"trace {trace_id} not found")
    return spans


async def load_spans(session: AsyncSession, trace_id: str) -> list[SpanOut]:
    rows = await session.scalars(
        select(Span).where(Span.trace_id == trace_id).order_by(Span.start_time, Span.span_id)
    )
    return [SpanOut.model_validate(s) for s in rows]


async def _read_body(request: Request) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(413, f"body is larger than {MAX_BODY_BYTES} bytes")

    encoding = request.headers.get("content-encoding", "identity").lower()
    if encoding == "identity":
        return bytes(body)
    if encoding != "gzip":
        raise HTTPException(415, "content encoding must be gzip or none")
    decompressor = zlib.decompressobj(wbits=31)
    try:
        data = decompressor.decompress(bytes(body), MAX_BODY_BYTES + 1)
    except zlib.error as e:
        raise HTTPException(400, f"body is not valid gzip: {e}") from e
    if len(data) > MAX_BODY_BYTES or decompressor.unconsumed_tail:
        raise HTTPException(413, f"body is larger than {MAX_BODY_BYTES} bytes once unzipped")
    return data


def _parse_protobuf(body: bytes) -> ExportTraceServiceRequest:
    export = ExportTraceServiceRequest()
    export.ParseFromString(body)
    return export


def _parse_json(body: bytes) -> ExportTraceServiceRequest:
    """Parse OTLP JSON.

    OTLP JSON writes trace and span ids as hex, but protobuf's JSON parser reads bytes fields
    as base64. Parsed as is, a hex id either fails or quietly turns into a different id. So the
    ids are converted to base64 first.
    """
    data = json.loads(body)
    for resource_spans in data.get("resourceSpans", []):
        for scope_spans in resource_spans.get("scopeSpans", []):
            for span in scope_spans.get("spans", []):
                _hex_ids_to_base64(span)
                for link in span.get("links", []):
                    _hex_ids_to_base64(link)
    export = ExportTraceServiceRequest()
    json_format.ParseDict(data, export, ignore_unknown_fields=True)
    return export


def _hex_ids_to_base64(item: dict[str, Any]) -> None:
    for key in ("traceId", "spanId", "parentSpanId"):
        if item.get(key):
            try:
                raw = bytes.fromhex(item[key])
            except ValueError as e:
                raise ValueError(f"{key} must be hex, got {item[key]!r}") from e
            item[key] = base64.b64encode(raw).decode()


def _rows(export: ExportTraceServiceRequest) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    rejected = 0
    for resource_spans in export.resource_spans:
        resource = _attributes(resource_spans.resource.attributes)
        service = str(resource.get("service.name", "unknown"))
        for scope_spans in resource_spans.scope_spans:
            for span in scope_spans.spans:
                if len(span.trace_id) != 16 or len(span.span_id) != 8:
                    rejected += 1
                    continue
                start = span.start_time_unix_nano
                rows.append(
                    {
                        "trace_id": span.trace_id.hex(),
                        "span_id": span.span_id.hex(),
                        "parent_span_id": span.parent_span_id.hex() or None,
                        "name": _clean(span.name),
                        "service_name": _clean(service),
                        "start_time": EPOCH + timedelta(microseconds=start // 1000),
                        "duration_ns": max(0, span.end_time_unix_nano - start),
                        "status": STATUS.get(span.status.code, "unset"),
                        "status_message": _clean(span.status.message) or None,
                        "attributes": _attributes(span.attributes),
                    }
                )
    return rows, rejected


def _attributes(pairs: Iterable[KeyValue]) -> dict[str, Any]:
    return {_clean(kv.key): _value(kv.value) for kv in pairs}


def _value(value: AnyValue) -> Any:
    kind = value.WhichOneof("value")
    if kind is None:
        return None
    if kind == "array_value":
        return [_value(v) for v in value.array_value.values]
    if kind == "kvlist_value":
        return _attributes(value.kvlist_value.values)
    if kind == "bytes_value":
        return base64.b64encode(value.bytes_value).decode()
    if kind == "string_value":
        return _clean(value.string_value)
    if kind == "double_value" and not math.isfinite(value.double_value):
        # JSONB has no NaN or infinity.
        return str(value.double_value)
    return getattr(value, kind)


def _clean(text: str) -> str:
    # Postgres text and JSONB can't hold the NUL character and reject the whole insert.
    return text.replace("\x00", "")
