"""Spike-only official middleware extension shared by Lead and SubAgent graphs."""

import asyncio
import json
import threading
import time
import traceback
from decimal import Decimal

from langchain.agents.middleware import AgentMiddleware
from langchain_core.utils.function_calling import convert_to_openai_tool


class P2AgentBudgetGuard(AgentMiddleware):
    lock = threading.Lock()
    admissions = []
    outcomes = []
    # Includes JSON-serialized message and tool schemas plus protocol reserve.
    INPUT_BYTES = 90000
    INPUT_TOKEN_BOUND = INPUT_BYTES + 8192
    OUTPUT_TOKENS = 1024
    MAX_CALLS = 7
    PRIOR_OCCUPANCY_USD = Decimal("0.0519855")
    RESERVED_USD = (
        Decimal(MAX_CALLS)
        * (Decimal(INPUT_TOKEN_BOUND) * Decimal("0.10") + Decimal(OUTPUT_TOKENS) * Decimal("0.50"))
        / Decimal(1_000_000)
    )

    def _admit(self, request):
        model = request.model
        if (
            model.model_name != "gpt-6-luna"
            or not model.use_responses_api
            or model.max_retries != 0
            or model.max_tokens != self.OUTPUT_TOKENS
        ):
            raise RuntimeError("P2 agent model budget settings rejected")
        if str(model.root_client.base_url) != "https://api.openai.com/v1/":
            raise RuntimeError("P2 requires official endpoint")
        if request.response_format is not None or request.model_settings:
            raise RuntimeError("P2 agent settings override rejected")
        messages = ([request.system_message] if request.system_message else []) + list(
            request.messages
        )
        if len(messages) > 24 or any(not self._text_content(m.content) for m in messages):
            raise RuntimeError("P2 agent permits bounded text only")
        schemas = []
        for tool in request.tools:
            if getattr(tool, "name", None) != "task":
                raise RuntimeError("P2 agent only permits native task tool")
            schemas.append(convert_to_openai_tool(tool))
        serialized = json.dumps(
            {"messages": [m.model_dump(mode="json") for m in messages], "tools": schemas},
            ensure_ascii=True,
        ).encode()
        if len(serialized) > self.INPUT_BYTES:
            raise RuntimeError("P2 agent input budget exceeded")
        if self.PRIOR_OCCUPANCY_USD + self.RESERVED_USD > Decimal("10"):
            raise RuntimeError("P2 cumulative budget exceeded")
        with self.lock:
            if len(self.admissions) >= self.MAX_CALLS:
                raise RuntimeError("P2 agent model call count exceeded")
            self.admissions.append(
                {
                    "request_bytes": len(serialized),
                    "tools": [t.name for t in request.tools],
                    "messages": [m.content for m in messages],
                    # Python 3.12/Windows monotonic uses coarse GetTickCount64;
                    # high-resolution intervals avoid false zero-duration overlap.
                    "started": time.perf_counter(),
                    "finished": None,
                    "loop_id": id(asyncio.get_running_loop()) if self._has_loop() else None,
                    "thread_id": threading.get_ident(),
                    "client_id": id(
                        getattr(getattr(model, "root_async_client", None), "_client", None)
                    ),
                }
            )
            return len(self.admissions) - 1

    @staticmethod
    def _has_loop():
        try:
            asyncio.get_running_loop()
            return True
        except RuntimeError:
            return False

    @staticmethod
    def _text_content(content):
        if isinstance(content, str):
            return True
        if not isinstance(content, list):
            return False
        allowed = {
            "text": {"type", "text", "annotations", "id", "index", "phase"},
            "function_call": {"type", "name", "arguments", "id", "call_id", "status", "index"},
        }
        for block in content:
            if not isinstance(block, dict) or block.get("type") not in allowed:
                return False
            if set(block) - allowed[block["type"]]:
                return False
            if block["type"] == "text":
                if not isinstance(block.get("text"), str) or block.get("annotations"):
                    return False
            elif block.get("name") != "task" or not isinstance(block.get("arguments"), str):
                return False
        return True

    def _error(self, index, exc):
        chain = []
        current = exc
        while current is not None and len(chain) < 6:
            chain.append(type(current).__name__)
            current = current.__cause__
        self.admissions[index]["error_types"] = chain
        self.admissions[index]["http_status"] = getattr(exc, "status_code", None)
        if "CancelledError" in chain:
            category = "cancelled"
        elif getattr(exc, "status_code", None) is not None:
            category = "http_api"
        elif "APITimeoutError" in chain:
            category = "timeout"
        elif any(t in chain for t in ("APIConnectionError", "ConnectError", "ReadError")):
            category = "client_connection"
        elif any(
            t in chain
            for t in (
                "JSONDecodeError",
                "ValidationError",
                "AttributeError",
                "TypeError",
                "ValueError",
            )
        ):
            category = "response_or_model_parse"
        else:
            category = "model_handler"
        self.admissions[index]["error_category"] = category
        self.admissions[index]["error_frames"] = [
            frame.name for frame in traceback.extract_tb(exc.__traceback__)
        ]

    def _record(self, result, index=None):
        for message in getattr(result, "result", []):
            for call in getattr(message, "tool_calls", []):
                args = call.get("args", {})
                if (
                    call.get("name") != "task"
                    or args.get("subagent_type") not in ("lab", "research", "procurement")
                    or args.get("context_mode", "isolated") != "isolated"
                    or args.get("model_name") is not None
                ):
                    raise RuntimeError("P2 delegation boundary rejected")
            with self.lock:
                self.outcomes.append(
                    {
                        "content": message.content,
                        "tool_calls": getattr(message, "tool_calls", []),
                        "usage": getattr(message, "usage_metadata", None),
                        "response": getattr(message, "response_metadata", None),
                        "admission_index": index,
                    }
                )
        return result

    def wrap_model_call(self, request, handler):
        index = self._admit(request)
        try:
            return self._record(handler(request), index)
        except BaseException as exc:
            self._error(index, exc)
            raise
        finally:
            self.admissions[index]["finished"] = time.perf_counter()

    async def awrap_model_call(self, request, handler):
        index = self._admit(request)
        try:
            return self._record(await handler(request), index)
        except BaseException as exc:
            self._error(index, exc)
            raise
        finally:
            self.admissions[index]["finished"] = time.perf_counter()
