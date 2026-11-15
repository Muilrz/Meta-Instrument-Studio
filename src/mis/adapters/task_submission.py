"""Durable command ordering around the thin HTTP adapter; never auto-resends."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy.engine import Engine

from mis.adapters.deerflow import DeerFlowClient, ThreadBinding
from mis.adapters.task_bridge import brief_hash, brief_payload, check_thread, start_task_run
from mis.adapters.task_store import (
    CallBudget,
    CommandIntent,
    CommandRecord,
    PostgresTaskRunLinkStore,
)
from mis.schemas.tasks import AgentTaskBrief


class DurableTaskSubmission:
    """Requires an independently approved/installed schema and authorized brief.

    Transactions end before HTTP. The budget snapshot is an audit reservation,
    not enforcement: the runtime must still install its shared admission guard.
    Losing the process after intent commit sacrifices automatic delivery in
    favour of avoiding duplicate paid calls. Reconciliation is read-only HTTP.
    """

    def __init__(self, engine: Engine, *, store_factory=PostgresTaskRunLinkStore):
        self.engine = engine
        self.store_factory = store_factory

    def submit(
        self,
        client: DeerFlowClient,
        brief: AgentTaskBrief,
        thread: ThreadBinding,
        run_id: str,
        *,
        idempotency_key: str,
        config_sha256: str,
        budget: CallBudget,
    ) -> CommandRecord:
        check_thread(brief, thread)
        if brief.status == "stale":
            raise ValueError("stale brief rejected")
        # Fingerprint the semantic command, including immutable deployment
        # identity, not a mutable usage/status snapshot or upstream response.
        command = {
            "brief": brief_payload(brief),
            "thread": vars(thread),
            "run_id": run_id,
            "idempotency_key": idempotency_key,
            "config_sha256": config_sha256,
            "agent_name": "project-copilot",
            "subagent_enabled": True,
        }
        fingerprint = hashlib.sha256(
            json.dumps(command, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        intent = CommandIntent(
            thread,
            run_id,
            idempotency_key,
            brief_hash(brief),
            brief.baseline_version,
            brief.specialist,
            config_sha256,
            fingerprint,
            budget,
        )
        with self.engine.begin() as connection:
            receipt = self.store_factory(connection).begin_intent(intent)
        if not receipt.created:
            return receipt.command
        # Commit uncertainty BEFORE sending. A crash anywhere from this point
        # leaves a reloadable command that cannot be implicitly submitted again.
        with self.engine.begin() as connection:
            self.store_factory(connection).mark_uncertain(thread.project_id, run_id)
        result, _ = start_task_run(client, brief, thread, run_id, idempotency_key=idempotency_key)
        with self.engine.begin() as connection:
            return self.store_factory(connection).reconcile(thread.project_id, run_id, result)

    def reconcile(self, client: DeerFlowClient, project_id: str, run_id: str) -> CommandRecord:
        with self.engine.begin() as connection:
            record = self.store_factory(connection).get_command(project_id, run_id)
        if record.upstream_run_id is not None:
            result = client.get_run(record.link.binding)
        else:
            result = client.find_run(record.intent.thread, run_id)
        if result is None:
            # Absence is not permission to POST, even after an upstream crash.
            return record
        with self.engine.begin() as connection:
            return self.store_factory(connection).reconcile(project_id, run_id, result)
