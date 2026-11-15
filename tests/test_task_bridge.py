import json
from dataclasses import replace

import httpx
import pytest

from mis.adapters.deerflow import DeerFlowClient, RunBinding, RunEvent, ThreadBinding
from mis.adapters.task_bridge import (
    TaskRunLink,
    brief_hash,
    event_envelope,
    receive_artifact,
    start_task_run,
)


def context(records):
    _, _, brief, _, artifact, *_ = records
    binding = RunBinding(ThreadBinding(brief.project_id, brief.id, "mt", "dt"), "mr", "dr")
    link = TaskRunLink(binding, brief_hash(brief), brief.baseline_version, brief.specialist)
    artifact = artifact.model_copy(
        update={
            "produced_by": artifact.produced_by.model_copy(
                update={"run_id": "mr", "actor": "procurement"}
            )
        }
    )
    return brief, link, artifact


def test_task_brief_routes_to_configured_copilot_with_correlation(records):
    brief, link, _ = context(records)

    def handler(request):
        if request.method == "GET":
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
        body = json.loads(request.content)
        assert body["context"] == {"agent_name": "project-copilot", "subagent_enabled": True}
        assert body["metadata"]["mis_task_id"] == brief.id
        content = json.loads(body["input"]["messages"][0]["content"])
        assert content["brief_sha256"] == link.brief_sha256
        assert content["mis_task_brief"]["specialist"] == "procurement"
        assert "usage" not in content["mis_task_brief"]
        assert "status" not in content["mis_task_brief"]
        assert request.headers["Idempotency-Key"] == "command-1"
        return httpx.Response(
            200,
            json={
                "thread_id": "dt",
                "run_id": "dr",
                "status": "pending",
                "metadata": body["metadata"],
            },
        )

    with DeerFlowClient(
        "https://gateway.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        result, actual = start_task_run(
            client, brief, link.binding.thread, "mr", idempotency_key="command-1"
        )
    assert actual == link
    assert result.status == "queued"


@pytest.mark.parametrize("change", [{"project_id": "other"}, {"task_id": "other"}])
def test_wrong_scope_rejected_before_network(records, change):
    brief, link, _ = context(records)

    def handler(request):
        pytest.fail("must not send a cross-scope request")

    with DeerFlowClient(
        "https://gateway.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(ValueError, match="scope"):
            start_task_run(
                client, brief, replace(link.binding.thread, **change), "mr", idempotency_key="c"
            )


def test_changed_brief_cannot_receive_existing_run_artifact(records):
    brief, link, artifact = context(records)
    with pytest.raises(ValueError, match="snapshot"):
        receive_artifact(
            artifact.model_dump(mode="json"), brief.model_copy(update={"goal": "changed"}), link
        )


def test_draft_receipt_does_not_adopt_or_write(records):
    brief, link, artifact = context(records)
    assert receive_artifact(artifact.model_dump(mode="json"), brief, link) == artifact


@pytest.mark.parametrize(
    "change",
    [
        {"project_id": "other"},
        {"brief_id": "other"},
        {"status": "accepted"},
        {"requirement_refs": ["unassigned"]},
        {"produced_by": {"run_id": "other", "actor": "procurement"}},
        {"produced_by": {"run_id": "mr", "actor": "lab"}},
    ],
)
def test_cross_scope_or_promoted_artifact_rejected(records, change):
    brief, link, artifact = context(records)
    with pytest.raises(ValueError):
        receive_artifact({**artifact.model_dump(mode="json"), **change}, brief, link)


def test_event_envelope_never_exposes_payload_or_infers_terminal_status(records):
    _, link, _ = context(records)
    event = RunEvent(
        link.binding, "stream.closed", None, {"secret": "private"}, {"data": "private"}
    )
    envelope = event_envelope(event, link)
    assert envelope["type"] == "stream.closed"
    assert "status" not in envelope
    assert "private" not in json.dumps(envelope)
    assert envelope["task_id"] == link.binding.thread.task_id
    with pytest.raises(ValueError, match="mapping"):
        event_envelope(replace(event, binding=replace(link.binding, run_id="other")), link)


def test_profile_validation_precedes_network(records):
    _, link, _ = context(records)
    with DeerFlowClient(
        "https://gateway.invalid", transport=httpx.MockTransport(lambda r: pytest.fail("network"))
    ) as client:
        with pytest.raises(ValueError, match="agent_name"):
            client.start_run(
                link.binding.thread, "mr", [], idempotency_key="c", agent_name="../other"
            )


def test_subagents_require_explicit_profile(records):
    _, link, _ = context(records)
    with DeerFlowClient(
        "https://gateway.invalid", transport=httpx.MockTransport(lambda r: pytest.fail("network"))
    ) as client:
        with pytest.raises(ValueError, match="explicit"):
            client.start_run(
                link.binding.thread, "mr", [], idempotency_key="c", enable_subagents=True
            )


def test_remote_thread_scope_checked_before_post(records):
    from mis.adapters.deerflow import DeerFlowError

    brief, link, _ = context(records)
    requests = []

    def handler(request):
        requests.append(request.method)
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "thread_id": "dt",
                "metadata": {
                    "mis_project_id": "another-project",
                    "mis_task_id": brief.id,
                    "mis_thread_id": "mt",
                },
            },
        )

    with DeerFlowClient(
        "https://gateway.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(DeerFlowError, match="thread_mapping_conflict"):
            start_task_run(client, brief, link.binding.thread, "mr", idempotency_key="c")
    assert requests == ["GET"]


@pytest.mark.parametrize("missing", ["artifact", "claim"])
def test_receipt_rejects_missing_stable_ids_instead_of_generating_on_replay(records, missing):
    brief, link, artifact = context(records)
    payload = artifact.model_dump(mode="json")
    if missing == "artifact":
        del payload["id"]
    else:
        del payload["claims"][0]["claim_id"]
    with pytest.raises(ValueError, match="stable"):
        receive_artifact(payload, brief, link)
