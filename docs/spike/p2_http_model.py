"""Offline-only ChatOpenAI model provider using a public http_async_client hook.

The Responses SDK and LangChain serializers run normally. HTTP is intercepted
before any socket connection. Never select this provider for a live request.
"""

import asyncio
import json
import threading

import httpx

from mis.agents.responses_model import IsolatedResponsesModel, ModelAsyncClient

ROLES = ("lab", "research", "procurement")
BARRIER = threading.Barrier(3, timeout=15)


def _response(request):
    payload = json.loads(request.content)
    text = json.dumps(payload)
    role = next((r for r in ROLES if f"You are MIS {r} Specialist." in text), None)
    if role:
        BARRIER.wait()
        content = json.dumps(
            {
                "role": role,
                "task_id": f"task-{role}",
                "summary": f"{role} fixed candidate",
                "evidence_refs": [f"EV-{role}"],
                "unknowns": ["unverified"],
            }
        )
        output = [
            {
                "id": f"msg-{role}",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": content, "annotations": []}],
            }
        ]
    elif any(item.get("type") == "function_call_output" for item in payload.get("input", [])):
        output = [
            {
                "id": "msg-summary",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps({"summaries": list(ROLES), "status": "unreviewed"}),
                        "annotations": [],
                    }
                ],
            }
        ]
    else:
        output = [
            {
                "id": f"fc-{r}",
                "type": "function_call",
                "status": "completed",
                "call_id": f"call-{r}",
                "name": "task",
                "arguments": json.dumps(
                    {
                        "subagent_type": r,
                        "context_mode": "isolated",
                        "prompt": json.dumps(
                            {
                                "role": r,
                                "task_id": f"task-{r}",
                                "canary": f"CANARY-{r}",
                                "evidence_refs": [f"EV-{r}"],
                            }
                        ),
                    }
                ),
            }
            for r in ROLES
        ]
    return httpx.Response(
        200,
        request=request,
        json={
            "id": "resp-offline-" + output[0]["id"],
            "object": "response",
            "created_at": 0,
            "status": "completed",
            "model": "gpt-6-luna",
            "output": output,
            "usage": {
                "input_tokens": 10,
                "output_tokens": 10,
                "total_tokens": 20,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 0},
            },
        },
    )


async def _transport(request):
    response = await asyncio.to_thread(_response, request)
    if not json.loads(request.content).get("stream"):
        return response
    body = response.json()
    events = [
        {"type": "response.created", "response": {**body, "output": [], "status": "in_progress"}}
    ]
    for index, item in enumerate(body["output"]):
        events.append(
            {
                "type": "response.output_item.added",
                "output_index": index,
                "item": {**item, "arguments": ""} if item["type"] == "function_call" else item,
            }
        )
        if item["type"] == "function_call":
            events.append(
                {
                    "type": "response.function_call_arguments.delta",
                    "output_index": index,
                    "item_id": item["id"],
                    "delta": item["arguments"],
                }
            )
        else:
            events.append(
                {
                    "type": "response.output_text.delta",
                    "output_index": index,
                    "content_index": 0,
                    "item_id": item["id"],
                    "delta": item["content"][0]["text"],
                }
            )
    events.append({"type": "response.completed", "response": body})
    data = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)
    return httpx.Response(200, content=data, headers={"Content-Type": "text/event-stream"})


class OfflineResponsesModel(IsolatedResponsesModel):
    @classmethod
    def create_http_client(cls, timeout):
        return ModelAsyncClient(timeout=timeout, transport=httpx.MockTransport(_transport))

    def __init__(self, **kwargs):
        kwargs["disable_streaming"] = not kwargs.get("streaming", False)
        super().__init__(**kwargs)
