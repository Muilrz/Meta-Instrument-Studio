"""Zero-external-network Responses diagnostics in the pinned upstream environment.

Uses official SDKs with MockTransport, plus a loopback HTTP/1.1 keepalive server.
No real credentials, model calls, database, Sandbox, or upstream mutations.
"""

import asyncio
import json
import logging
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import httpx
from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI


def response_body(text="fixture"):
    return {
        "id": "resp-fixture",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": "gpt-6-luna",
        "output": [
            {
                "id": "msg-fixture",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
        "usage": {
            "input_tokens": 10,
            "output_tokens": 2,
            "total_tokens": 12,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def sse_bytes():
    body = response_body()
    item = body["output"][0]
    events = [
        {"type": "response.created", "response": {**body, "status": "in_progress", "output": []}},
        {"type": "response.output_item.added", "output_index": 0, "item": item},
        {
            "type": "response.output_text.delta",
            "output_index": 0,
            "content_index": 0,
            "item_id": item["id"],
            "delta": "fixture",
        },
        {
            "type": "response.output_text.done",
            "output_index": 0,
            "content_index": 0,
            "item_id": item["id"],
            "text": "fixture",
        },
        {"type": "response.completed", "response": body},
    ]
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def safe_error(exc):
    chain = []
    current = exc
    while current and len(chain) < 6:
        chain.append(type(current).__name__)
        current = current.__cause__
    return {"types": chain, "status": getattr(exc, "status_code", None)}


async def sdk_cases():
    calls = []

    async def success(request):
        calls.append(json.loads(request.content).get("stream", False))
        if calls[-1]:
            return httpx.Response(
                200, content=sse_bytes(), headers={"Content-Type": "text/event-stream"}
            )
        return httpx.Response(200, json=response_body())

    client = httpx.AsyncClient(transport=httpx.MockTransport(success))
    model = ChatOpenAI(
        model="gpt-6-luna",
        api_key="offline",
        use_responses_api=True,
        output_version="responses/v1",
        max_retries=0,
        http_async_client=client,
    )
    normal = await model.ainvoke("fixture")
    streamed = [chunk async for chunk in model.astream("fixture")]
    assert "fixture" in str(normal.content) and "fixture" in str([c.content for c in streamed])
    await asyncio.gather(*(model.ainvoke(f"parallel-{i}") for i in range(3)))
    await client.aclose()
    results = {"nonstream_and_stream": "PASS", "shared_client_same_loop_concurrency": "PASS"}

    cases = {
        "http_401": lambda r: httpx.Response(
            401, json={"error": {"message": "fixture", "type": "auth", "code": "fixture"}}
        ),
        "http_503": lambda r: httpx.Response(
            503, json={"error": {"message": "fixture", "type": "server", "code": "fixture"}}
        ),
        "connect_error": lambda r: (_ for _ in ()).throw(httpx.ConnectError("fixture", request=r)),
        "read_timeout": lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("fixture", request=r)),
        "response_parse": lambda r: httpx.Response(
            200, json={"id": "fixture", "output": "invalid"}
        ),
    }
    for name, fn in cases.items():
        attempted = []

        def handler(request, action=fn, entries=attempted):
            entries.append(True)
            return action(request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
            failing = ChatOpenAI(
                model="gpt-6-luna",
                api_key="offline",
                use_responses_api=True,
                max_retries=0,
                http_async_client=transport,
            )
            try:
                await failing.ainvoke("fixture")
            except Exception as exc:
                results[name] = {**safe_error(exc), "transport_entries": len(attempted)}
            else:
                raise AssertionError(f"{name} should fail")
    closed_entries = []
    closed = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: closed_entries.append(True)))
    await closed.aclose()
    sdk = AsyncOpenAI(api_key="offline", max_retries=0, http_client=closed)
    try:
        await sdk.responses.create(model="gpt-6-luna", input="fixture")
    except Exception as exc:
        results["closed_client_before_send"] = {
            **safe_error(exc),
            "transport_entries": len(closed_entries),
        }
        assert not closed_entries
    else:
        raise AssertionError("closed client should fail")

    class BrokenStream(httpx.AsyncByteStream):
        def __init__(self, malformed=False):
            self.malformed = malformed
            self.closed = False

        async def __aiter__(self):
            if self.malformed:
                yield b"event: response.output_text.delta\ndata: invalid-json\n\n"
            else:
                yield (
                    b'event: response.created\ndata: {"type":"response.created",'
                    b'"response":{"id":"resp-broken"}}\n\n'
                )
                raise httpx.ReadError("fixture midstream read")

        async def aclose(self):
            self.closed = True

    for malformed in (False, True):
        broken = BrokenStream(malformed)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r, value=broken: httpx.Response(
                    200, stream=value, headers={"Content-Type": "text/event-stream"}
                )
            )
        ) as transport:
            sdk = AsyncOpenAI(api_key="offline", max_retries=0, http_client=transport)
            try:
                response = await sdk.responses.create(
                    model="gpt-6-luna", input="fixture", stream=True
                )
                async with response:
                    async for _ in response:
                        pass
            except Exception as exc:
                results["stream_bad_json" if malformed else "stream_read_error"] = {
                    **safe_error(exc),
                    "headers_status": 200,
                }
            else:
                raise AssertionError("broken stream should fail")
            assert broken.closed

    class BlockingStream(httpx.AsyncByteStream):
        closed = False
        entered = asyncio.Event()

        async def __aiter__(self):
            self.entered.set()
            yield (
                b'event: response.created\ndata: {"type":"response.created",'
                b'"response":{"id":"resp-cancel"}}\n\n'
            )
            await asyncio.Event().wait()

        async def aclose(self):
            self.closed = True

    stream = BlockingStream()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, stream=stream, headers={"Content-Type": "text/event-stream"}
            )
        )
    ) as transport:
        sdk = AsyncOpenAI(api_key="offline", max_retries=0, http_client=transport)

        async def consume():
            result = await sdk.responses.create(model="gpt-6-luna", input="fixture", stream=True)
            async with result:
                async for _ in result:
                    pass

        task = asyncio.create_task(consume())
        await stream.entered.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert stream.closed
        results["stream_cancel_cleanup"] = "PASS: CancelledError propagates; stream closed"
    return results


def keepalive_cross_loop():
    from mis.agents.responses_model import IsolatedResponsesModel, close_model_clients

    hits = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            hits.append(threading.get_ident())
            body = response_body()
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}/v1"
    model = ChatOpenAI(
        model="gpt-6-luna",
        api_key="offline",
        base_url=base,
        use_responses_api=True,
        max_retries=0,
        timeout=5,
    )
    same = ChatOpenAI(
        model="gpt-6-luna",
        api_key="offline",
        base_url=base,
        use_responses_api=True,
        max_retries=0,
        timeout=5,
    )
    assert model.root_async_client._client is same.root_async_client._client
    result = {"shared_default_client": True}
    try:
        asyncio.run(model.ainvoke("loop-one"))
        before = len(hits)
        try:
            asyncio.run(same.ainvoke("loop-two"))
        except Exception as exc:
            result["second_loop"] = {**safe_error(exc), "server_new_requests": len(hits) - before}
        else:
            result["second_loop"] = "PASS"

        async def fresh():
            try:
                separate = IsolatedResponsesModel(
                    model="gpt-6-luna",
                    api_key="offline",
                    base_url=base,
                    use_responses_api=True,
                    max_retries=0,
                )
                return await separate.ainvoke("fresh-loop")
            finally:
                await close_model_clients()

        for _ in range(2):
            assert "fixture" in str(asyncio.run(fresh()).content)
        result["fresh_clients_separate_loops"] = "PASS"
        active_loop = asyncio.new_event_loop()
        active_thread = threading.Thread(target=active_loop.run_forever, daemon=True)
        active_thread.start()
        first = ChatOpenAI(
            model="gpt-6-luna",
            api_key="offline",
            base_url=base,
            use_responses_api=True,
            max_retries=0,
            timeout=5.1,
        )
        second = ChatOpenAI(
            model="gpt-6-luna",
            api_key="offline",
            base_url=base,
            use_responses_api=True,
            max_retries=0,
            timeout=5.1,
        )
        try:
            asyncio.run_coroutine_threadsafe(first.ainvoke("active-one"), active_loop).result(10)
            before = len(hits)
            try:
                asyncio.run(second.ainvoke("active-two"))
            except Exception as exc:
                result["active_loop_shared_client"] = {
                    **safe_error(exc),
                    "server_new_requests": len(hits) - before,
                }
            else:
                result["active_loop_shared_client"] = "PASS"
        finally:
            active_loop.call_soon_threadsafe(active_loop.stop)
            active_thread.join(5)
            active_loop.close()
    finally:
        server.shutdown()
        server.server_close()
    return result


def main():
    logging.disable(logging.CRITICAL)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    connect = socket.socket.connect

    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return connect(sock, address)
        raise AssertionError("external network forbidden")

    with patch.object(socket.socket, "connect", local_only):
        results = {
            "sdk_cases": asyncio.run(sdk_cases()),
            "keepalive_cross_loop": keepalive_cross_loop(),
        }
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
