"""Pure A4 resume preflight; storage and authorization belong to MIS services."""

from dataclasses import dataclass
from typing import Any

from mis.adapters.deerflow import RunBinding
from mis.schemas.evidence import Evidence
from mis.schemas.questions import UserQuestion


@dataclass(frozen=True)
class PauseBinding:
    """Question pause; interrupt_id is observed audit evidence, not a stable cursor."""

    run: RunBinding
    question_id: str
    checkpoint_id: str
    interrupt_id: str
    pending_node: str


def reconcile_a4_status(
    run_status: str,
    checkpoint_state: dict[str, Any] | None,
    *,
    pending_interrupt_id: str | None,
) -> str:
    """Reconcile command completion with the separately inspected graph state.

    The caller proves that the pending interrupt belongs to its stored Question.
    The native Run can say ``success`` while its graph is durably interrupted.
    This is graph progress only; ``completed`` does not adopt an Artifact or Plan.
    """
    if (
        not checkpoint_state
        or not checkpoint_state.get("checkpoint_id")
        or not isinstance(checkpoint_state.get("next"), list)
    ):
        return "unknown"
    if checkpoint_state["next"]:
        return "waiting_user" if pending_interrupt_id else "unknown"
    if pending_interrupt_id:
        return "unknown"
    return {
        "success": "completed",
        "error": "failed",
        "timeout": "failed",
        "pending": "queued",
        "running": "running",
    }.get(run_status, "unknown")


def resume_request(
    pause: PauseBinding,
    question: UserQuestion,
    evidence: Evidence,
    *,
    answer: str,
    resume_key: str,
    resume_run_id: str,
    current_checkpoint_id: str,
    observed_interrupt_id: str,
    current_pending_nodes: tuple[str, ...],
) -> dict[str, Any]:
    """Build the pinned native command only after checking trusted stored records.

    Callers load question/Evidence from authorized MIS storage and persist the
    resume command before I/O. A matching supplied object is not proof of storage.
    The caller must atomically serialize competing answers and reconcile uncertain
    HTTP outcomes. This function cannot grant authorization or exactly-once writes.
    The pinned Gateway can rewrite a metadata-only checkpoint after interruption;
    its native interrupt ID then changes. Scalar resume is deliberately limited to
    one known Question and its single pending node. Arbitrary multi-interrupt graphs
    require another binding and are not supported by this helper.
    """
    if (
        not pause.checkpoint_id
        or not pause.interrupt_id
        or pause.checkpoint_id != current_checkpoint_id
        or pause.interrupt_id != observed_interrupt_id
        or not pause.pending_node
        or current_pending_nodes != (pause.pending_node,)
        or pause.question_id != question.id
        or question.run_id != pause.run.run_id
        or question.project_id != pause.run.thread.project_id
        or question.status != "answered"
        or question.answer != answer
        or question.answer_evidence_id != evidence.id
        or (question.options and answer not in question.options)
        or not answer.strip()
        or evidence.project_id != question.project_id
        or evidence.source_type != "user_decision"
        or evidence.retrieved_by.actor != "user"
        or evidence.retrieved_by.run_id != question.run_id
        or evidence.excerpt != answer
        or evidence.locator != question.id
        or evidence.page_or_anchor != "answer"
        or not resume_key
        or not resume_run_id.strip()
        or resume_run_id == pause.run.run_id
        or len(resume_key) > 255
        or any(not 32 <= ord(char) <= 126 for char in resume_key)
    ):
        raise ValueError("A4 answer/checkpoint/Evidence binding rejected")
    response = {
        "question_id": question.id,
        "checkpoint_id": pause.checkpoint_id,
        "answer_evidence_id": evidence.id,
        "resume_key": resume_key,
        "answer": answer,
        "observed_interrupt_id": pause.interrupt_id,
    }
    return {
        "assistant_id": "lead_agent",
        # The pinned Gateway's metadata-only duration checkpoints can change
        # native task/interrupt IDs. Scalar resume is supported only after the
        # single-question / single-pending-node checks above; the old ID is audit.
        "command": {"resume": response},
        "checkpoint_id": pause.checkpoint_id,
        "metadata": {
            "mis_project_id": pause.run.thread.project_id,
            "mis_task_id": pause.run.thread.task_id,
            "mis_thread_id": pause.run.thread.thread_id,
            "mis_run_id": resume_run_id,
            "mis_parent_run_id": pause.run.run_id,
            "mis_question_id": question.id,
            "mis_answer_evidence_id": evidence.id,
            "mis_resume_key": resume_key,
        },
        "context": {"subagent_enabled": False, "thinking_enabled": False},
        "multitask_strategy": "reject",
    }
