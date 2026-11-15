"""Optional DeerFlow provider: isolated SDK clients through public constructor hooks.

Import only in the pinned DeerFlow environment; MIS business code does not depend
on LangChain. A client belongs to one model and one event loop, never the global
LangChain HTTP-client cache. Request telemetry excludes body, URL and credentials.
"""

import asyncio
import json
import threading
import time

import httpx
from langchain_openai import ChatOpenAI


class ModelAsyncClient(httpx.AsyncClient):
    instances = []
    registry_lock = threading.Lock()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.owner_loop = None
        self.owner_lock = threading.Lock()
        self.events = []
        with self.registry_lock:
            self.instances.append(self)

    async def send(self, request, **kwargs):
        loop = asyncio.get_running_loop()
        with self.owner_lock:
            if self.owner_loop is None:
                self.owner_loop = loop
            if self.owner_loop is not loop:
                raise RuntimeError("model HTTP client cannot cross event loops")
        event = {
            "started": time.perf_counter(),
            "response_status": None,
            "loop_id": id(loop),
            "request_bytes": len(request.content),
            "stream": bool(json.loads(request.content).get("stream", False)),
        }
        self.events.append(event)
        try:
            response = await super().send(request, **kwargs)
            event["response_status"] = response.status_code
            return response
        except BaseException as exc:
            event["error_type"] = type(exc).__name__
            raise
        finally:
            event["headers_finished"] = time.perf_counter()


class IsolatedResponsesModel(ChatOpenAI):
    """One explicit http_async_client per model; no changes to native scheduling."""

    @classmethod
    def create_http_client(cls, timeout):
        return ModelAsyncClient(timeout=timeout)

    def __init__(self, **kwargs):
        if kwargs.get("http_async_client") is not None:
            raise ValueError("isolated model owns its asynchronous HTTP client")
        kwargs["http_async_client"] = self.create_http_client(kwargs.get("timeout", 30))
        super().__init__(**kwargs)


async def close_model_clients():
    """Close each pool on its original loop before the parent loop shuts down."""
    loop = asyncio.get_running_loop()
    for client in list(ModelAsyncClient.instances):
        if client.is_closed:
            continue
        owner = client.owner_loop
        if owner is None or owner is loop:
            await client.aclose()
        elif owner.is_running():
            await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(client.aclose(), owner))
        else:
            raise RuntimeError("model owner loop stopped before client cleanup")
