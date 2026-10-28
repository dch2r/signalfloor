import base64
import gzip
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from google.protobuf import json_format
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, ArrayValue, KeyValue, KeyValueList
from opentelemetry.proto.trace.v1.trace_pb2 import ResourceSpans, ScopeSpans, Span, Status

from signalfloor_server.traces import MAX_BODY_BYTES

TRACE = bytes.fromhex("5b8efff798038103d269b633813fc60c")
ROOT = bytes.fromhex("eee19b7ec3c1b174")
CHILD = bytes.fromhex("eee19b7ec3c1b175")
START = 1_761_670_800_000_000_000  # 2025-10-28 17:00:00 UTC in nanoseconds
PROTOBUF = {"content-type": "application/x-protobuf"}
JSON = {"content-type": "application/json"}


def kv(key: str, **value: Any) -> KeyValue:
    return KeyValue(key=key, value=AnyValue(**value))


def span(
    span_id: bytes = ROOT,
    parent: bytes = b"",
    name: str = "invoke_agent",
    *,
    trace_id: bytes = TRACE,
    start_ms: int = 0,
    duration_ns: int = 2_500_000,
    attributes: list[KeyValue] | None = None,
    status: Status | None = None,
) -> Span:
    start = START + start_ms * 1_000_000
    return Span(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent,
        name=name,
        start_time_unix_nano=start,
        end_time_unix_nano=start + duration_ns,
        attributes=attributes or [],
        status=status or Status(),
    )


def export(*spans: Span, service: str = "signalfloor-agent") -> ExportTraceServiceRequest:
    request = ExportTraceServiceRequest()
    resource_spans = ResourceSpans(scope_spans=[ScopeSpans(spans=spans)])
    resource_spans.resource.attributes.append(kv("service.name", string_value=service))
    request.resource_spans.append(resource_spans)
    return request


def otlp_json(request: ExportTraceServiceRequest) -> str:
    """OTLP JSON. Like protobuf's JSON form, except ids are hex instead of base64."""
    body = json.loads(json_format.MessageToJson(request))
    for resource_spans in body["resourceSpans"]:
        for item in resource_spans["scopeSpans"][0]["spans"]:
            for key in ("traceId", "spanId", "parentSpanId"):
                if key in item:
                    item[key] = base64.b64decode(item[key]).hex()
    return json.dumps(body)


def send(client: TestClient, request: ExportTraceServiceRequest) -> Any:
    return client.post("/v1/traces", content=request.SerializeToString(), headers=PROTOBUF)


def test_protobuf_spans_are_stored_and_served(client: TestClient) -> None:
    response = send(
        client,
        export(
            span(ROOT, name="invoke_agent", duration_ns=2_500_000),
            span(
                CHILD,
                ROOT,
                "execute_tool search",
                start_ms=1,
                status=Status(code=Status.STATUS_CODE_ERROR, message="timed out"),
            ),
        ),
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/x-protobuf"
    reply = ExportTraceServiceResponse()
    reply.ParseFromString(response.content)
    assert reply.partial_success.rejected_spans == 0

    root, child = client.get(f"/traces/{TRACE.hex()}").json()
    assert root["trace_id"] == "5b8efff798038103d269b633813fc60c"
    assert root["span_id"] == "eee19b7ec3c1b174"
    assert root["parent_span_id"] is None
    assert root["name"] == "invoke_agent"
    assert root["service_name"] == "signalfloor-agent"
    assert root["start_time"] == "2025-10-28T17:00:00Z"
    assert root["duration_ms"] == 2.5
    assert root["status"] == "unset"
    assert child["parent_span_id"] == "eee19b7ec3c1b174"
    assert child["status"] == "error"
    assert child["status_message"] == "timed out"


def test_attribute_values(client: TestClient) -> None:
    attributes = [
        kv("gen_ai.request.model", string_value="qwen3:1.7b"),
        kv("gen_ai.usage.input_tokens", int_value=812),
        kv("score", double_value=0.5),
        kv("bad", double_value=float("nan")),
        kv("hit_limit", bool_value=True),
        kv("titles", array_value=ArrayValue(values=[AnyValue(string_value="Paris")])),
        kv("nested", kvlist_value=KeyValueList(values=[kv("k", int_value=1)])),
        kv("raw", bytes_value=b"\x00\x01"),
        kv("empty"),
        kv("nul", string_value="a\x00b"),
    ]
    send(client, export(span(attributes=attributes, name="chat\x00")))

    (stored,) = client.get(f"/traces/{TRACE.hex()}").json()

    assert stored["attributes"] == {
        "gen_ai.request.model": "qwen3:1.7b",
        "gen_ai.usage.input_tokens": 812,
        "score": 0.5,
        "bad": "nan",
        "hit_limit": True,
        "titles": ["Paris"],
        "nested": {"k": 1},
        "raw": "AAE=",
        "empty": None,
        "nul": "ab",
    }
    assert stored["name"] == "chat"


def test_json_ids_are_hex_not_base64(client: TestClient) -> None:
    body = json.loads(otlp_json(export(span(ROOT), span(CHILD, ROOT, "chat"))))
    body["resourceSpans"][0]["scopeSpans"][0]["spans"][1]["links"] = [
        {"traceId": TRACE.hex(), "spanId": ROOT.hex()}
    ]

    response = client.post("/v1/traces", content=json.dumps(body), headers=JSON)

    assert response.status_code == 200
    assert response.json() == {}
    spans = client.get(f"/traces/{TRACE.hex()}").json()
    assert [(s["span_id"], s["parent_span_id"]) for s in spans] == [
        ("eee19b7ec3c1b174", None),
        ("eee19b7ec3c1b175", "eee19b7ec3c1b174"),
    ]


def test_protobuf_style_base64_ids_are_refused_in_json(client: TestClient) -> None:
    # The mistake a naive parser makes in reverse: base64 ids are not hex, so they fail loudly
    # instead of being stored as different ids.
    response = client.post(
        "/v1/traces", content=json_format.MessageToJson(export(span())), headers=JSON
    )

    assert response.status_code == 400
    assert "must be hex" in response.json()["detail"]


def test_resent_spans_are_stored_once(client: TestClient) -> None:
    request = export(span())

    send(client, request)
    send(client, request)

    assert len(client.get(f"/traces/{TRACE.hex()}").json()) == 1


def test_gzipped_body(client: TestClient) -> None:
    response = client.post(
        "/v1/traces",
        content=gzip.compress(export(span()).SerializeToString()),
        headers={**PROTOBUF, "content-encoding": "gzip"},
    )

    assert response.status_code == 200
    assert client.get(f"/traces/{TRACE.hex()}").status_code == 200


def test_spans_with_bad_ids_are_rejected_not_the_whole_batch(client: TestClient) -> None:
    response = send(client, export(span(), span(b"short", trace_id=b"x")))

    assert response.status_code == 200
    reply = ExportTraceServiceResponse()
    reply.ParseFromString(response.content)
    assert reply.partial_success.rejected_spans == 1
    assert "16 byte trace id" in reply.partial_success.error_message
    assert len(client.get(f"/traces/{TRACE.hex()}").json()) == 1


def test_partial_success_in_json(client: TestClient) -> None:
    response = client.post("/v1/traces", content=otlp_json(export(span(b"\x01\x02"))), headers=JSON)

    assert response.status_code == 200
    assert response.json()["partialSuccess"]["rejectedSpans"] == "1"


def test_spans_without_a_service_name(client: TestClient) -> None:
    request = ExportTraceServiceRequest(
        resource_spans=[ResourceSpans(scope_spans=[ScopeSpans(spans=[span()])])]
    )

    send(client, request)

    assert client.get(f"/traces/{TRACE.hex()}").json()[0]["service_name"] == "unknown"


@pytest.mark.parametrize(
    ("body", "headers", "status", "message"),
    [
        (b"{}", {"content-type": "text/plain"}, 415, "content type must be"),
        (b"{}", {**JSON, "content-encoding": "br"}, 415, "content encoding"),
        (b"not gzip", {**JSON, "content-encoding": "gzip"}, 400, "not valid gzip"),
        (b"\xff\xff\xff", PROTOBUF, 400, "not a valid OTLP"),
        (b"{not json", JSON, 400, "not a valid OTLP"),
        (b"[]", JSON, 400, "not a valid OTLP"),
        (b'{"resourceSpans": 5}', JSON, 400, "not a valid OTLP"),
        (
            b'{"resourceSpans": [{"scopeSpans": [{"spans": [{"traceId": "zz"}]}]}]}',
            JSON,
            400,
            "traceId must be hex",
        ),
    ],
)
def test_bad_requests(
    client: TestClient, body: bytes, headers: dict[str, str], status: int, message: str
) -> None:
    response = client.post("/v1/traces", content=body, headers=headers)

    assert response.status_code == status
    assert message in response.json()["detail"]


def test_body_size_limit(client: TestClient) -> None:
    response = client.post("/v1/traces", content=b"x" * (MAX_BODY_BYTES + 1), headers=PROTOBUF)

    assert response.status_code == 413


def test_gzip_bomb_is_refused(client: TestClient) -> None:
    # About 10 KB on the wire, 11 MB once unzipped.
    bomb = gzip.compress(b"\x00" * (MAX_BODY_BYTES + 1_000_000))
    assert len(bomb) < 20_000

    response = client.post(
        "/v1/traces", content=bomb, headers={**PROTOBUF, "content-encoding": "gzip"}
    )

    assert response.status_code == 413
    assert "once unzipped" in response.json()["detail"]


def test_missing_trace(client: TestClient) -> None:
    assert client.get(f"/traces/{'0' * 32}").status_code == 404


def test_trace_ids_are_case_insensitive(client: TestClient) -> None:
    send(client, export(span()))

    assert client.get(f"/traces/{TRACE.hex().upper()}").status_code == 200


def test_case_with_its_trace(client: TestClient) -> None:
    cases = [{"id": "q0", "score": 1.0, "trace_id": TRACE.hex()}, {"id": "q1", "score": 0.0}]
    run_id = client.post("/runs", json={"name": "traced", "cases": cases}).json()["id"]
    send(client, export(span()))

    traced = client.get(f"/runs/{run_id}/cases/q0").json()
    untraced = client.get(f"/runs/{run_id}/cases/q1").json()

    assert traced["score"] == 1.0
    assert traced["trace_id"] == TRACE.hex()
    assert [s["name"] for s in traced["spans"]] == ["invoke_agent"]
    assert untraced == {"case_id": "q1", "score": 0.0, "trace_id": None, "spans": []}
