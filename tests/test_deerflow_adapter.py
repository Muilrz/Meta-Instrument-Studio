import json
from dataclasses import asdict

import httpx
import pytest

from mis.adapters.deerflow import (
    DeerFlowClient,
    DeerFlowError,
    RunBinding,
    ThreadBinding,
    normalize_status,
)


@pytest.fixture
def binding():
    return RunBinding(ThreadBinding("p1", "task1", "mt1", "dt1"), "mr1", "dr1")


def test_thread_mapping_is_stable_and_uses_mis_metadata():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.path == "/api/threads"
        assert request.headers["Authorization"] == "Bearer test-token"
        body = json.loads(request.content)
        assert body["metadata"]["mis_project_id"] == "p"
        assert body["metadata"]["mis_thread_id"] == "mt"
        assert "project_id" not in body  # MIS IDs never target DeerFlow Projects.
        return httpx.Response(200, json=body)

    with DeerFlowClient(
        "https://gateway.invalid", token="test-token", transport=httpx.MockTransport(handler)
    ) as client:
        first = client.create_thread("p", "task", "mt")
        assert first == client.create_thread("p", "task", "mt")
        assert asdict(first)["project_id"] == "p"
        assert first != client.create_thread("p", "other-task", "mt")
    assert len(requests) == 3


def test_thread_conflicting_existing_mapping_is_rejected():
    def handler(request):
        body = json.loads(request.content)
        return httpx.Response(200, json={**body, "metadata": {}})

    with DeerFlowClient(
        "https://gateway.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(DeerFlowError, match="thread_mapping_conflict"):
            client.create_thread("p", "t", "mt")


@pytest.mark.parametrize("mismatch", [None, "thread", "metadata", "missing_metadata"])
def test_get_thread_checks_mapping_and_preserves_upstream_fields(binding, mismatch):
    payload = {
        "thread_id": "dt1",
        "status": "idle",
        "metadata": {
            "mis_project_id": "p1",
            "mis_task_id": "task1",
            "mis_thread_id": "mt1",
        },
        "values": {"messages": []},
    }
    if mismatch == "thread":
        payload["thread_id"] = "other"
    elif mismatch == "metadata":
        payload["metadata"]["mis_task_id"] = "other"
    elif mismatch == "missing_metadata":
        del payload["metadata"]

    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/api/threads/dt1"
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(200, json=payload)

    with DeerFlowClient(
        "https://gateway.invalid", token="test-token", transport=httpx.MockTransport(handler)
    ) as client:
        if mismatch:
            with pytest.raises(DeerFlowError, match="thread_mapping_conflict") as exc:
                client.get_thread(binding.thread)
            assert exc.value.raw == payload
        else:
            assert client.get_thread(binding.thread) == payload


def test_start_query_and_cancel_preserve_binding_and_do_not_infer_cancellation(binding):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/cancel"):
            assert dict(request.url.params) == {"action": "interrupt", "wait": "true"}
            return httpx.Response(204)
        if request.method == "POST":
            assert request.headers["Idempotency-Key"] == "command-1"
            body = json.loads(request.content)
            assert body["metadata"]["mis_run_id"] == "mr1"
            assert body["input"] == {"messages": [{"type": "human", "content": "hello"}]}
            status = "pending"
        else:
            status = "interrupted"
        return httpx.Response(
            200,
            json={
                "thread_id": "dt1",
                "run_id": "dr1",
                "status": status,
                "metadata": {
                    "mis_project_id": "p1",
                    "mis_task_id": "task1",
                    "mis_thread_id": "mt1",
                    "mis_run_id": "mr1",
                },
            },
        )

    with DeerFlowClient(
        "https://gateway.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        result = client.start_run(
            binding.thread,
            "mr1",
            [{"type": "human", "content": "hello"}],
            idempotency_key="command-1",
        )
        assert result.status == "queued"
        assert result.binding == binding
        assert client.cancel_run(binding, wait=True) is None
        result = client.get_run(binding)
        assert result.status == "unknown"
        assert result.raw["status"] == "interrupted"
    assert len(requests) == 3


@pytest.mark.parametrize("status", ["success", "error", "timeout", "new_upstream_status"])
def test_status_mapping(status):
    assert normalize_status(status) == {
        "success": "completed",
        "error": "failed",
        "timeout": "failed",
    }.get(status, "unknown")


def test_http_error_keeps_detail_without_logging_or_retries(binding):
    calls = []
    detail = {"detail": {"code": "conflict", "message": "private upstream detail"}}

    def handler(request):
        calls.append(request)
        return httpx.Response(409, json=detail)

    with DeerFlowClient(
        "https://gateway.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(DeerFlowError) as error:
            client.get_run(binding)
    assert error.value.raw == detail
    assert error.value.status == 409
    assert "private upstream detail" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "error_type,kind", [(httpx.ReadTimeout, "timeout"), (httpx.ConnectError, "transport_error")]
)
def test_transport_failures_are_safe_and_not_retried(binding, error_type, kind):
    calls = []

    def handler(request):
        calls.append(request)
        raise error_type("private headers and endpoint", request=request)

    with DeerFlowClient(
        "https://gateway.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(DeerFlowError) as error:
            client.get_run(binding)
    assert error.value.kind == kind
    assert "private" not in str(error.value)
    assert len(calls) == 1


def test_json_protocol_and_cross_thread_errors(binding):
    for response, kind in [
        (httpx.Response(200, text="not JSON"), "invalid_json"),
        (httpx.Response(200, json=[]), "invalid_response"),
        (
            httpx.Response(200, json={"thread_id": "other", "run_id": "dr1", "status": "success"}),
            "run_mapping_conflict",
        ),
    ]:
        with DeerFlowClient(
            "https://gateway.invalid",
            transport=httpx.MockTransport(lambda request, response=response: response),
        ) as client:
            with pytest.raises(DeerFlowError) as error:
                client.get_run(binding)
        assert error.value.kind == kind


def test_sse_multiline_comments_unknown_error_and_end_preserve_raw(binding):
    body = (
        ": heartbeat\r\n\r\n"
        'event: metadata\r\nid: 1\r\ndata: {"run_id":\r\ndata: "dr1"}\r\n\r\n'
        'event: messages/partial\ndata: [{"content":"Hi"}]\n\n'
        "event: future-event\ndata: plain text\n\n"
        'event: error\ndata: {"detail":"model failed"}\n\n'
        "event: end\ndata: null\n\n"
    )

    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/api/threads/dt1/runs/dr1/stream"
        return httpx.Response(200, text=body, headers={"Content-Type": "text/event-stream"})

    with DeerFlowClient(
        "https://gateway.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        events = list(client.stream_events(binding))
    assert [e.event_type for e in events] == [
        "run.updated",
        "message.delta",
        "runtime.event",
        "run.error",
        "stream.closed",
    ]
    assert events[0].data == {"run_id": "dr1"}
    assert events[0].event_id == "1"
    assert events[0].raw["data"] == '{"run_id":\n"dr1"}'
    assert events[2].raw["event"] == "future-event"
    assert events[3].data == {"detail": "model failed"}
    assert all(e.binding == binding for e in events)


@pytest.mark.parametrize(
    "body,limit,kind",
    [
        ("data: unfinished", 100, "truncated_event"),
        ("data: long event\n\n", 4, "event_too_large"),
    ],
)
def test_bad_streams_fail_explicitly(binding, body, limit, kind):
    def handler(request):
        return httpx.Response(200, text=body, headers={"Content-Type": "text/event-stream"})

    with DeerFlowClient(
        "https://gateway.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(DeerFlowError) as error:
            list(client.stream_events(binding, max_event_bytes=limit))
    assert error.value.kind == kind


def test_redirect_does_not_forward_credentials(binding):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://another.invalid"})

    with DeerFlowClient(
        "https://gateway.invalid", token="secret", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(DeerFlowError) as error:
            client.get_run(binding)
    assert error.value.status == 302
    assert len(calls) == 1


def test_invalid_ids_and_keys_make_no_request(binding):
    def handler(request):
        pytest.fail("invalid inputs must not leave the process")

    with DeerFlowClient(
        "https://gateway.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(ValueError):
            client.create_thread("", "t", "mt")
        for key in [" ", "key\nInjected: header", "非ASCII"]:
            with pytest.raises(ValueError):
                client.start_run(binding.thread, "mr1", [], idempotency_key=key)


def test_replayed_create_run_keeps_key_and_mapping_across_client_instances(binding):
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append((request.headers["Idempotency-Key"], body))
        return httpx.Response(
            200,
            json={
                "thread_id": "dt1",
                "run_id": "dr1",
                "status": "pending",
                "metadata": body["metadata"],
            },
        )

    for _ in range(2):
        with DeerFlowClient(
            "https://gateway.invalid", transport=httpx.MockTransport(handler)
        ) as client:
            result = client.start_run(binding.thread, "mr1", [], idempotency_key="same-action")
            assert result.binding == binding
    assert requests[0] == requests[1]


def test_reused_key_returning_another_mis_run_is_rejected(binding):
    def handler(request):
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "thread_id": "dt1",
                "run_id": "dr1",
                "status": "pending",
                "metadata": {**body["metadata"], "mis_run_id": "another-run"},
            },
        )

    with DeerFlowClient(
        "https://gateway.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(DeerFlowError, match="run_mapping_conflict"):
            client.start_run(binding.thread, "mr1", [], idempotency_key="reused")


def test_stream_checks_deadline_and_releases_response(binding, monkeypatch):
    times = iter([0, 2])
    monkeypatch.setattr("mis.adapters.deerflow.monotonic", lambda: next(times))
    response = httpx.Response(
        200, text="data: null\n\n", headers={"Content-Type": "text/event-stream"}
    )
    with DeerFlowClient(
        "https://gateway.invalid", transport=httpx.MockTransport(lambda request: response)
    ) as client:
        with pytest.raises(DeerFlowError, match="stream_deadline"):
            list(client.stream_events(binding, max_seconds=1))
    assert response.is_closed


@pytest.mark.parametrize(
    "response,kind",
    [
        (httpx.Response(503, json={"detail": "unavailable"}), "http_error"),
        (
            httpx.Response(200, text="html", headers={"Content-Type": "text/html"}),
            "invalid_stream_content_type",
        ),
    ],
)
def test_stream_rejects_http_and_content_type_errors(binding, response, kind):
    with DeerFlowClient(
        "https://gateway.invalid", transport=httpx.MockTransport(lambda request: response)
    ) as client:
        with pytest.raises(DeerFlowError) as error:
            list(client.stream_events(binding))
    assert error.value.kind == kind
