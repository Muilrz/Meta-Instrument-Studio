"""Offline-only official SDK transport for premature Lead finalization."""

import asyncio
import json
import os
import re
import threading
from uuid import uuid4

import httpx

from mis.agents.profiles import SPECIALISTS
from mis.agents.responses_model import IsolatedResponsesModel, ModelAsyncClient

BARRIER = threading.Barrier(2, timeout=15)
OBSERVATIONS = []


def answer(messages):
    text = "\n".join(str(m) for m in messages)
    role = next((r for r in SPECIALISTS if f"You are MIS {r} Specialist." in text), None)
    if role:
        OBSERVATIONS.append((role, text))
        if role != "lab":
            BARRIER.wait()
        brief_id = re.search(r"brf_[0-9A-HJKMNP-TV-Z]{26}", text).group()
        evidence_id = re.search(r"evd_[0-9A-HJKMNP-TV-Z]{26}", text).group()
        return {
            "role": role,
            "task_id": brief_id,
            "summary": "fixed 500 mW source",
            "unknowns": [],
            "claims": [
                {
                    "statement": "source power",
                    "subject": "FIXTURE-" + role,
                    "metric": "laser.max_power",
                    "value": {
                        "kind": "known",
                        "value": {"value": 500, "unit": "mW"},
                        "evidence_ids": [evidence_id],
                    },
                }
            ],
        }
    count = sum(isinstance(m, dict) and m.get("type") == "function_call_output" for m in messages)
    if count == 0:
        return None
    roles = ["lab"] if count == 1 else list(SPECIALISTS)
    return {
        "roles": roles,
        "summaries": {r: "fixed 500 mW source" for r in roles},
        "status": "unreviewed",
    }


def response(request):
    payload = json.loads(request.content)
    value = answer(payload.get("input", []))
    if (
        os.environ.get("P2E_OFFLINE_FAILURE") == "research"
        and value
        and value.get("role") == "research"
    ):
        return httpx.Response(
            503,
            request=request,
            json={"error": {"message": "offline fault", "type": "server_error"}},
        )
    uid = uuid4().hex
    if value is None:
        output = [
            {
                "id": "fc-" + uid,
                "type": "function_call",
                "status": "completed",
                "call_id": "lead-lab-" + uid,
                "name": "task",
                "arguments": json.dumps(
                    {
                        "subagent_type": "lab",
                        "context_mode": "isolated",
                        "prompt": "Only lab, intentionally omit other roles",
                    }
                ),
            }
        ]
    else:
        output = [
            {
                "id": "msg-" + uid,
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": json.dumps(value), "annotations": []}],
            }
        ]
    return httpx.Response(
        200,
        request=request,
        json={
            "id": "resp-" + uid,
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


async def transport(request):
    return await asyncio.to_thread(response, request)


class OfflineCompletionModel(IsolatedResponsesModel):
    @classmethod
    def create_http_client(cls, timeout):
        return ModelAsyncClient(timeout=timeout, transport=httpx.MockTransport(transport))
