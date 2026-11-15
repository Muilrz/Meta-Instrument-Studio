"""Business correlation for the pinned DeerFlow transport; no execution engine.

The caller authorizes the brief and persists command intent before network I/O.
No database writes, automatic adoption, or implicit retries happen here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from mis.adapters.deerflow import DeerFlowClient, RunBinding, RunEvent, RunResult, ThreadBinding
from mis.schemas.artifacts import AgentArtifact
from mis.schemas.tasks import AgentTaskBrief


def brief_payload(brief: AgentTaskBrief) -> dict[str, Any]:
    """Only the assigned task, never sibling history or mutable accounting."""
    return brief.model_dump(mode="json", exclude={"usage", "status", "status_history"})


def brief_hash(brief: AgentTaskBrief) -> str:
    body = json.dumps(
        brief_payload(brief), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def check_thread(brief: AgentTaskBrief, thread: ThreadBinding) -> None:
    if thread.project_id != brief.project_id or thread.task_id != brief.id:
        raise ValueError("brief/thread scope mismatch")


@dataclass(frozen=True)
class TaskRunLink:
    binding: RunBinding
    brief_sha256: str
    baseline_version: int
    specialist: str

    def check(self, brief: AgentTaskBrief) -> None:
        check_thread(brief, self.binding.thread)
        if (
            self.brief_sha256 != brief_hash(brief)
            or self.baseline_version != brief.baseline_version
            or self.specialist != brief.specialist
        ):
            raise ValueError("brief snapshot mismatch")


class TaskRunLinkStore(Protocol):
    """Future durable store: unique MIS run and upstream run; immutable insert.

    A repeated identical put must return the existing record; any changed mapping
    must fail atomically. Implementation and command-intent/outbox remain pending.
    """

    def put(self, link: TaskRunLink) -> TaskRunLink: ...

    def get(self, project_id: str, run_id: str) -> TaskRunLink: ...


def start_task_run(
    client: DeerFlowClient,
    brief: AgentTaskBrief,
    thread: ThreadBinding,
    run_id: str,
    *,
    idempotency_key: str,
) -> tuple[RunResult, TaskRunLink]:
    """Submit a trusted brief to Copilot; role routing belongs to native Runtime.

    This does not enforce model budgets: the server must install a deterministic
    shared admission guard before a real request. No arbitrary Runtime config is
    accepted from the brief. Persist the returned link before follow-up commands.
    """
    check_thread(brief, thread)
    if brief.status == "stale":
        raise ValueError("stale brief rejected")
    # A locally supplied binding is not evidence that the remote Thread owns
    # this project/brief. Verify before a model can read its persisted history.
    client.get_thread(thread)
    content = json.dumps(
        {"mis_task_brief": brief_payload(brief), "brief_sha256": brief_hash(brief)},
        ensure_ascii=False,
        sort_keys=True,
    )
    result = client.start_run(
        thread,
        run_id,
        [{"type": "human", "content": content}],
        idempotency_key=idempotency_key,
        agent_name="project-copilot",
        enable_subagents=True,
    )
    return result, TaskRunLink(
        result.binding, brief_hash(brief), brief.baseline_version, brief.specialist
    )


def receive_artifact(
    payload: dict[str, Any], brief: AgentTaskBrief, link: TaskRunLink
) -> AgentArtifact:
    """Validate a draft candidate; ProjectService still checks Evidence and rules.

    Never infer a business Artifact from an SSE values/end event or a file path.
    This is a pure receiving boundary, not ProjectService.add or acceptance.
    """
    link.check(brief)
    return validate_artifact_candidate(payload, brief, link.binding.run_id)


def validate_artifact_candidate(
    payload: dict[str, Any], brief: AgentTaskBrief, run_id: str
) -> AgentArtifact:
    """Shared draft checks after the caller verifies a standalone or bundle binding."""
    artifact = AgentArtifact.model_validate(payload)
    if not payload.get("id") or any(
        not isinstance(claim, dict) or not claim.get("claim_id")
        for claim in payload.get("claims", [])
    ):
        raise ValueError("runtime artifacts require stable artifact and claim IDs")
    if (
        brief.status == "stale"
        or artifact.project_id != brief.project_id
        or artifact.brief_id != brief.id
        or artifact.produced_by.run_id != run_id
        or artifact.produced_by.actor != brief.specialist
        or not set(artifact.requirement_refs) <= set(brief.requirement_refs)
        or artifact.status != "draft"
        or artifact.status_history
    ):
        raise ValueError("artifact scope or draft provenance mismatch")
    return artifact


def event_envelope(event: RunEvent, link: TaskRunLink) -> dict[str, Any]:
    """Versioned correlation only; raw model/tool payload stays internal.

    event_id is a source cursor, possibly absent, not a durable MIS dedupe key.
    Terminal success requires a separate authoritative get_run reconciliation.
    """
    if event.binding != link.binding:
        raise ValueError("event/run mapping mismatch")
    thread = link.binding.thread
    return {
        "contract_version": 1,
        "project_id": thread.project_id,
        "task_id": thread.task_id,
        "run_id": link.binding.run_id,
        "type": event.event_type,
        "source_event_id": event.event_id,
    }
