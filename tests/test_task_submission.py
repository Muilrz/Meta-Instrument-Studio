from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import Mock

import httpx
import pytest

from mis.adapters.deerflow import DeerFlowClient, DeerFlowError, ThreadBinding
from mis.adapters.task_store import CallBudget, CommandRecord, IntentReceipt
from mis.adapters.task_submission import DurableTaskSubmission


class TransactionProbe:
    def __init__(self, events):
        self.events = events
        self.active = False

    @contextmanager
    def begin(self):
        self.active = True
        try:
            yield self
        finally:
            self.active = False
            self.events.append("commit")


def test_intent_and_uncertain_commit_before_post_and_failure_never_reposts(records):
    brief = records[2]
    thread = ThreadBinding(brief.project_id, brief.id, "mt", "dt")
    events = []
    engine = TransactionProbe(events)
    store = Mock()
    held = {}

    def begin(intent):
        if "record" in held:
            return IntentReceipt(False, held["record"])
        held["record"] = CommandRecord(intent, "intent")
        events.append("intent")
        return IntentReceipt(True, held["record"])

    def uncertain(*args):
        held["record"] = CommandRecord(held["record"].intent, "uncertain")
        events.append("uncertain")
        return held["record"]

    store.begin_intent.side_effect = begin
    store.mark_uncertain.side_effect = uncertain
    store.get_command.side_effect = lambda *args: held["record"]

    def handler(request):
        assert not engine.active
        if request.method == "GET":
            if request.url.path.endswith("/page"):
                return httpx.Response(200, json={"data": [], "has_more": False})
            return httpx.Response(
                200,
                json={
                    "thread_id": "dt",
                    "metadata": {
                        "mis_project_id": brief.project_id,
                        "mis_task_id": brief.id,
                        "mis_thread_id": "mt",
                    },
                },
            )
        events.append("post")
        assert events[:4] == ["intent", "commit", "uncertain", "commit"]
        raise httpx.ReadTimeout("response lost", request=request)

    runner = DurableTaskSubmission(engine, store_factory=lambda c: store)
    kwargs = {
        "idempotency_key": "stable-command",
        "config_sha256": "a" * 64,
        "budget": CallBudget(7, 98192, 1024, Decimal("0.0723184")),
    }
    with DeerFlowClient(
        "https://gateway.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(DeerFlowError, match="timeout"):
            runner.submit(client, brief, thread, "mr", **kwargs)
        assert held["record"].state == "uncertain"
        # Reconstruct a coordinator as a re-entry test; this is deliberately a
        # mocked ledger, not a claim of PostgreSQL cross-process persistence.
        reloaded = DurableTaskSubmission(engine, store_factory=lambda c: store)
        assert reloaded.submit(client, brief, thread, "mr", **kwargs).state == "uncertain"
        assert reloaded.reconcile(client, brief.project_id, "mr").state == "uncertain"
    assert events.count("post") == 1
    store.reconcile.assert_not_called()


def test_failed_intent_transaction_cannot_send_http(records):
    brief = records[2]
    store = Mock()
    store.begin_intent.side_effect = ValueError("conflict")
    runner = DurableTaskSubmission(TransactionProbe([]), store_factory=lambda c: store)
    client = Mock(spec=DeerFlowClient)
    with pytest.raises(ValueError, match="conflict"):
        runner.submit(
            client,
            brief,
            ThreadBinding(brief.project_id, brief.id, "mt", "dt"),
            "mr",
            idempotency_key="c",
            config_sha256="a" * 64,
            budget=CallBudget(7, 98192, 1024, Decimal("0.0723184")),
        )
    client.start_run.assert_not_called()
    client.get_thread.assert_not_called()
