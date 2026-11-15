"""HTTP boundary for DeerFlow v2.2.0 (58fc5bd).

Bindings are transport records, separate from P1 business models. The caller must
persist them before subsequent commands; this client owns no database or scheduler.
No operation retries automatically, including requests whose result is uncertain.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterator
from dataclasses import dataclass
from time import monotonic
from typing import Any
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

import httpx


class DeerFlowError(RuntimeError):
    """Safe summary with upstream detail available for controlled internal handling."""

    def __init__(self, kind: str, *, status: int | None = None, raw: Any = None):
        super().__init__(f"DeerFlow {kind}" + (f" (HTTP {status})" if status else ""))
        self.kind = kind
        self.status = status
        self.raw = raw


@dataclass(frozen=True)
class ThreadBinding:
    project_id: str
    task_id: str
    thread_id: str
    deerflow_thread_id: str


@dataclass(frozen=True)
class RunBinding:
    thread: ThreadBinding
    run_id: str
    deerflow_run_id: str


@dataclass(frozen=True)
class RunResult:
    binding: RunBinding
    status: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class RunEvent:
    binding: RunBinding
    event_type: str
    event_id: str | None
    data: Any
    raw: dict[str, str]


def normalize_status(status: str) -> str:
    """Interrupted needs checkpoint/question reconciliation before product mapping."""
    return {
        "pending": "queued",
        "running": "running",
        "success": "completed",
        "error": "failed",
        "timeout": "failed",
    }.get(status, "unknown")


def _segment(value: str) -> str:
    if not value or value in {".", ".."}:
        raise ValueError("IDs must be nonempty path segments")
    return quote(value, safe="")


class DeerFlowClient:
    """Synchronous, bounded HTTP client. Inject MockTransport for offline tests.

    Raw upstream payloads can contain private data. They are never interpolated
    into error messages and must be filtered before returning them through a BFF.
    """

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        timeout: float = 30,
        transport: httpx.BaseTransport | None = None,
    ):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive")
        url = httpx.URL(base_url)
        if url.scheme not in {"http", "https"} or url.userinfo or url.query or url.fragment:
            raise ValueError("base_url must be an HTTP service URL without credentials or query")
        self._client = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {token}"} if token else {},
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )
        self._timeout = timeout

    def __enter__(self) -> DeerFlowClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def _check(response: httpx.Response) -> None:
        if not 200 <= response.status_code < 300:
            try:
                raw = response.json()
            except ValueError:
                raw = response.text
            raise DeerFlowError("http_error", status=response.status_code, raw=raw)

    def _json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise DeerFlowError("timeout") from None
        except httpx.TransportError:
            raise DeerFlowError("transport_error") from None
        self._check(response)
        try:
            data = response.json()
        except ValueError:
            raise DeerFlowError("invalid_json", raw=response.text) from None
        if not isinstance(data, dict):
            raise DeerFlowError("invalid_response", raw=data)
        return data

    def create_thread(self, project_id: str, task_id: str, thread_id: str) -> ThreadBinding:
        for value in (project_id, task_id, thread_id):
            _segment(value)
        # Deterministic across restarts and uncertain create responses.
        identity = json.dumps([project_id, task_id, thread_id], separators=(",", ":"))
        upstream_id = str(uuid5(NAMESPACE_URL, "mis:deerflow:" + identity))
        metadata = {
            "mis_project_id": project_id,
            "mis_task_id": task_id,
            "mis_thread_id": thread_id,
        }
        data = self._json(
            "POST", "api/threads", json={"thread_id": upstream_id, "metadata": metadata}
        )
        returned_metadata = data.get("metadata")
        if (
            data.get("thread_id") != upstream_id
            or not isinstance(returned_metadata, dict)
            or any(returned_metadata.get(key) != value for key, value in metadata.items())
        ):
            raise DeerFlowError("thread_mapping_conflict", raw=data)
        return ThreadBinding(project_id, task_id, thread_id, upstream_id)

    def get_thread(self, binding: ThreadBinding) -> dict[str, Any]:
        """Read a thread and reject a response belonging to another MIS mapping."""
        data = self._json("GET", f"api/threads/{_segment(binding.deerflow_thread_id)}")
        metadata = data.get("metadata")
        expected = {
            "mis_project_id": binding.project_id,
            "mis_task_id": binding.task_id,
            "mis_thread_id": binding.thread_id,
        }
        if (
            data.get("thread_id") != binding.deerflow_thread_id
            or not isinstance(metadata, dict)
            or any(metadata.get(key) != value for key, value in expected.items())
        ):
            raise DeerFlowError("thread_mapping_conflict", raw=data)
        return data

    def start_run(
        self,
        thread: ThreadBinding,
        run_id: str,
        messages: list[dict[str, Any]],
        *,
        idempotency_key: str,
        assistant_id: str = "lead_agent",
        agent_name: str | None = None,
        enable_subagents: bool = False,
    ) -> RunResult:
        _segment(run_id)
        if agent_name is not None and not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", agent_name):
            raise ValueError("agent_name must be a deployment-owned profile name")
        if not isinstance(enable_subagents, bool) or (enable_subagents and agent_name is None):
            raise ValueError("subagents require an explicit deployment-owned agent profile")
        if (
            not idempotency_key.strip()
            or len(idempotency_key) > 255
            or any(not 32 <= ord(char) <= 126 for char in idempotency_key)
        ):
            raise ValueError("idempotency_key must contain 1–255 printable ASCII characters")
        data = self._json(
            "POST",
            f"api/threads/{_segment(thread.deerflow_thread_id)}/runs",
            headers={"Idempotency-Key": idempotency_key},
            json={
                "assistant_id": assistant_id,
                "input": {"messages": messages},
                "metadata": {
                    "mis_project_id": thread.project_id,
                    "mis_task_id": thread.task_id,
                    "mis_thread_id": thread.thread_id,
                    "mis_run_id": run_id,
                },
                "multitask_strategy": "reject",
                **(
                    {"context": {"agent_name": agent_name, "subagent_enabled": enable_subagents}}
                    if agent_name is not None
                    else {}
                ),
            },
        )
        upstream_run_id = data.get("run_id")
        if not isinstance(upstream_run_id, str) or not upstream_run_id:
            raise DeerFlowError("invalid_run_id", raw=data)
        binding = RunBinding(thread, run_id, upstream_run_id)
        return self._result(binding, data)

    @staticmethod
    def _run_path(binding: RunBinding) -> str:
        return (
            f"api/threads/{_segment(binding.thread.deerflow_thread_id)}"
            f"/runs/{_segment(binding.deerflow_run_id)}"
        )

    @staticmethod
    def _result(binding: RunBinding, data: dict[str, Any]) -> RunResult:
        if (
            data.get("run_id") != binding.deerflow_run_id
            or data.get("thread_id") != binding.thread.deerflow_thread_id
            or not isinstance(data.get("status"), str)
        ):
            raise DeerFlowError("run_mapping_conflict", raw=data)
        metadata = data.get("metadata")
        expected = {
            "mis_project_id": binding.thread.project_id,
            "mis_task_id": binding.thread.task_id,
            "mis_thread_id": binding.thread.thread_id,
            "mis_run_id": binding.run_id,
        }
        if not isinstance(metadata, dict) or any(
            metadata.get(key) != value for key, value in expected.items()
        ):
            raise DeerFlowError("run_mapping_conflict", raw=data)
        return RunResult(binding, normalize_status(data["status"]), data)

    def get_run(self, binding: RunBinding) -> RunResult:
        return self._result(binding, self._json("GET", self._run_path(binding)))

    def find_run(
        self, thread: ThreadBinding, run_id: str, *, max_pages: int = 5
    ) -> RunResult | None:
        """Read-only reconciliation after an uncertain POST; never resubmit.

        Scan bounded native keyset pages. A truncated scan is inconclusive,
        including when it contains one match: an unseen duplicate may exist.
        Absence does not authorize another model request.
        """
        _segment(run_id)
        if (
            isinstance(max_pages, bool)
            or not isinstance(max_pages, int)
            or not 1 <= max_pages <= 20
        ):
            raise ValueError("max_pages must be an integer from 1 to 20")
        self.get_thread(thread)
        params: dict[str, Any] = {"limit": 100}
        cursors = set()
        seen = set()
        matches = []
        for _ in range(max_pages):
            page = self._json(
                "GET", f"api/threads/{_segment(thread.deerflow_thread_id)}/runs/page", params=params
            )
            rows, more = page.get("data"), page.get("has_more")
            if not isinstance(rows, list) or not isinstance(more, bool):
                raise DeerFlowError("invalid_run_page", raw=page)
            for row in rows:
                if (
                    not isinstance(row, dict)
                    or row.get("thread_id") != thread.deerflow_thread_id
                    or not isinstance(row.get("run_id"), str)
                    or not row["run_id"]
                    or row["run_id"] in seen
                ):
                    raise DeerFlowError("invalid_run_page", raw=page)
                seen.add(row["run_id"])
                metadata = row.get("metadata")
                if isinstance(metadata, dict) and metadata.get("mis_run_id") == run_id:
                    binding = RunBinding(thread, run_id, row["run_id"])
                    matches.append(self._result(binding, row))
            if len(matches) > 1:
                raise DeerFlowError("ambiguous_run_mapping")
            if not more:
                return matches[0] if matches else None
            cursor = (page.get("next_before_created_at"), page.get("next_before_run_id"))
            if (
                any(not isinstance(value, str) or not value for value in cursor)
                or cursor in cursors
            ):
                raise DeerFlowError("invalid_run_cursor", raw=page)
            cursors.add(cursor)
            params.update(before_created_at=cursor[0], before_run_id=cursor[1])
        raise DeerFlowError("reconciliation_incomplete")

    def cancel_run(self, binding: RunBinding, *, wait: bool = False) -> None:
        """Request cancellation. Query get_run afterwards to reconcile actual state."""
        try:
            response = self._client.post(
                self._run_path(binding) + "/cancel",
                params={"action": "interrupt", "wait": str(wait).lower()},
            )
        except httpx.TimeoutException:
            raise DeerFlowError("timeout") from None
        except httpx.TransportError:
            raise DeerFlowError("transport_error") from None
        self._check(response)

    def stream_events(
        self, binding: RunBinding, *, max_seconds: float = 60, max_event_bytes: int = 1_000_000
    ) -> Iterator[RunEvent]:
        """Join a run stream. EOF/end indicates transport closure, never run success."""
        if not math.isfinite(max_seconds) or max_seconds <= 0 or max_event_bytes <= 0:
            raise ValueError("stream limits must be positive")
        deadline = monotonic() + max_seconds
        try:
            with self._client.stream(
                "GET",
                self._run_path(binding) + "/stream",
                timeout=min(self._timeout, max_seconds),
            ) as response:
                if not 200 <= response.status_code < 300:
                    response.read()
                    self._check(response)
                if "text/event-stream" not in response.headers.get("content-type", ""):
                    raise DeerFlowError("invalid_stream_content_type")
                fields: dict[str, str] = {}
                data_lines: list[str] = []
                size = 0
                for line in response.iter_lines():
                    if monotonic() > deadline:
                        raise DeerFlowError("stream_deadline")
                    size += len(line.encode("utf-8"))
                    if size > max_event_bytes:
                        raise DeerFlowError("event_too_large")
                    if not line:
                        if data_lines:
                            raw = {**fields, "data": "\n".join(data_lines)}
                            yield self._event(binding, raw)
                        fields, data_lines, size = {}, [], 0
                    elif not line.startswith(":"):
                        key, _, value = line.partition(":")
                        value = value.removeprefix(" ")
                        if key == "data":
                            data_lines.append(value)
                        elif key in {"event", "id"}:
                            fields[key] = value
                if data_lines:
                    raise DeerFlowError("truncated_event")
        except httpx.TimeoutException:
            raise DeerFlowError("timeout") from None
        except httpx.TransportError:
            raise DeerFlowError("transport_error") from None

    @staticmethod
    def _event(binding: RunBinding, raw: dict[str, str]) -> RunEvent:
        name = raw.get("event", "message")
        event_type = {
            "metadata": "run.updated",
            "messages": "message.delta",
            "messages/partial": "message.delta",
            "error": "run.error",
            "end": "stream.closed",
        }.get(name, "runtime.event")
        try:
            data = json.loads(raw["data"])
        except ValueError:
            data = raw["data"]
        return RunEvent(binding, event_type, raw.get("id"), data, raw)
