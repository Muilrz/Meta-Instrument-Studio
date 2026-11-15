import copy
import json
from decimal import Decimal

from mis.adapters.artifact_receiver import receive_bundle, request_hash
from mis.adapters.deerflow import ThreadBinding
from mis.adapters.task_store import CallBudget, CommandIntent, CommandRecord
from mis.agents.completion import AssignedTask
from mis.ids import new_id
from mis.project_service.repository import ProjectService
from mis.schemas.artifacts import AgentArtifact
from mis.schemas.plan import InstrumentPlan
from mis.schemas.tasks import SpecifiedParam, TaskBudget


def seed(service, records):
    project, baseline, base_brief, base_evidence, *_ = records
    service.add(project)
    service.add(baseline)
    assigned = []
    for role in ("lab", "research", "procurement"):
        brief = service.add(
            base_brief.model_copy(
                update={
                    "id": new_id("brf"),
                    "specialist": role,
                    "budget": TaskBudget(model_calls=1),
                    "specified_params": (
                        SpecifiedParam(
                            name="power", requirement_key="R04", target=baseline.items[0]
                        ),
                    ),
                }
            )
        )
        evidence = service.add(
            base_evidence.model_copy(
                update={
                    "id": new_id("evd"),
                    "excerpt": json.dumps(
                        {
                            "subject": "FIXTURE-" + role,
                            "metric": "laser.max_power",
                            "value": {"value": 500, "unit": "mW"},
                        }
                    ),
                }
            )
        )
        assigned.append(AssignedTask(brief, (evidence,)))
    body = {"input": {"mis_required_assignments": [a.dump() for a in assigned]}}
    anchor = assigned[0].brief
    from mis.adapters.task_bridge import brief_hash

    command = CommandRecord(
        CommandIntent(
            ThreadBinding(project.id, anchor.id, "mt", "dt"),
            "bundle-run",
            "command-key",
            brief_hash(anchor),
            1,
            "lab",
            "a" * 64,
            request_hash(body),
            CallBudget(7, 98192, 1024, Decimal("0.0723184")),
        ),
        "completed",
        "dr",
        "success",
    )
    return assigned, body, command


def messages_for(assignments, roles=None):
    messages = []
    for a in assignments:
        role = a.brief.specialist
        if roles is not None and role not in roles:
            continue
        call_id = "call-" + role
        payload = {
            "role": role,
            "task_id": a.brief.id,
            "summary": "fixed source",
            "claims": [
                {
                    "statement": "power",
                    "subject": "FIXTURE-" + role,
                    "metric": "laser.max_power",
                    "value": {
                        "kind": "known",
                        "value": {"value": 500, "unit": "mW"},
                        "evidence_ids": [a.evidence[0].id],
                    },
                }
            ],
        }
        messages.extend(
            [
                {
                    "type": "ai",
                    "tool_calls": [
                        {"id": call_id, "name": "task", "args": {"subagent_type": role}}
                    ],
                },
                {
                    "type": "tool",
                    "tool_call_id": call_id,
                    "additional_kwargs": {
                        "subagent_status": "completed",
                        "subagent_result_brief": json.dumps(payload),
                        "deerflow_tool_receipt": {
                            "tool_call_id": call_id,
                            "tool_name": "task",
                            "status": "success",
                        },
                    },
                },
            ]
        )
    messages.append(
        {
            "type": "ai",
            "content": json.dumps(
                {
                    "roles": [a.brief.specialist for a in assignments],
                    "summaries": {a.brief.specialist: "fixed source" for a in assignments},
                    "status": "unreviewed",
                }
            ),
        }
    )
    return messages


def changed_payload(messages, mutate):
    result = copy.deepcopy(messages)
    value = json.loads(result[1]["additional_kwargs"]["subagent_result_brief"])
    mutate(value)
    result[1]["additional_kwargs"]["subagent_result_brief"] = json.dumps(value)
    return result


def test_partial_then_complete_replayed_and_conflicting_business_reception(db_session, records):
    service = ProjectService(db_session)
    assignments, body, command = seed(service, records)
    partial = messages_for(assignments, {"lab", "research"})
    result = receive_bundle(service, command, body, partial)
    assert result["status"] == "partial"
    assert result["roles"]["procurement"]["status"] == "missing"
    assert len(service.list(AgentArtifact, records[0].id)) == 2
    assert receive_bundle(service, command, body, partial) == result
    complete = messages_for(assignments)
    received = receive_bundle(service, command, body, complete)
    assert received["status"] == "completed" and received["adoption"] == "unreviewed"
    assert receive_bundle(service, command, body, complete) == received
    assert len(service.list(AgentArtifact, records[0].id)) == 3
    assert all(a.status == "draft" for a in service.list(AgentArtifact, records[0].id))
    assert service.list(InstrumentPlan, records[0].id) == []
    for mutate in (
        lambda v: v["claims"][0].update(statement="different content same artifact ID"),
        lambda v: v["claims"][0]["value"]["value"].update(unit="V"),
        lambda v: v["claims"][0]["value"].update(evidence_ids=[assignments[1].evidence[0].id]),
        lambda v: v.update(task_id=assignments[1].brief.id),
    ):
        rejected = receive_bundle(service, command, body, changed_payload(complete, mutate))
        assert rejected["status"] == "partial"
        assert rejected["roles"]["lab"]["status"] == "failed"
    assert len(service.list(AgentArtifact, records[0].id)) == 3


def test_hard_constraint_failure_and_unknown_are_gaps_without_business_write(db_session, records):
    service = ProjectService(db_session)
    assignments, body, command = seed(service, records)
    complete = messages_for(assignments)
    # A dimensionally valid but unsupported fact cannot pass with a citation.
    bad = changed_payload(complete, lambda v: v["claims"][0]["value"]["value"].update(value=400))
    received = receive_bundle(service, command, body, bad)
    assert received["status"] == "partial" and received["roles"]["lab"]["status"] == "failed"
    assert len(service.list(AgentArtifact, records[0].id)) == 2
    unknown = changed_payload(
        complete,
        lambda v: v["claims"][0].update(value={"kind": "unknown", "reason": "missing power"}),
    )
    received = receive_bundle(service, command, body, unknown)
    assert received["roles"]["lab"]["gap"] == "hard_constraints_unknown"
    assert len(service.list(AgentArtifact, records[0].id)) == 2
