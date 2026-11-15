"""MIS reception of native Specialist receipts into unreviewed P1 drafts.

Caller authorizes the project, loads a durable command, and owns commit/rollback.
Raw messages must be fetched from that verified Runtime Run, never from a model
claim or user callback body alone. This module does not adopt plans or run agents.
"""

import hashlib
import json
import math

from ulid import ULID

from mis.adapters.task_bridge import validate_artifact_candidate
from mis.agents.completion import load_assignments
from mis.agents.completion_policy import complete_summary, execution_report
from mis.project_service.repository import ProjectService
from mis.rules.evaluate import evaluate
from mis.schemas.artifacts import AgentArtifact, Candidate, Claim
from mis.schemas.evidence import Evidence
from mis.schemas.project import InstrumentProject
from mis.schemas.provenance import RunRef
from mis.schemas.tasks import AgentTaskBrief
from mis.schemas.values import Known, Quantity, QuantityRange


def request_hash(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def stable_artifact_id(run_id, brief_id):
    raw = hashlib.sha256(json.dumps([run_id, brief_id]).encode()).digest()[:16]
    return "art_" + str(ULID.from_bytes(raw))


def result_json(message):
    text = (message.get("additional_kwargs") or {}).get("subagent_result_brief")
    if not isinstance(text, str):
        raise ValueError("native result brief is absent")
    if text.startswith("```json\n") and text.rstrip().endswith("```"):
        text = text.strip()[8:-3]
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Specialist result must be an object")
    return value


def _structured_support(claim, evidence):
    """Verify structured fixed-source facts when supplied; no general text judge."""
    facts = []
    for record in evidence:
        try:
            fact = json.loads(record.excerpt)
        except ValueError:
            continue
        if isinstance(fact, dict) and {"subject", "metric", "value"} <= fact.keys():
            facts.append((record.id, fact))
    if not facts or not isinstance(claim.value, Known):
        return
    for identifier, fact in facts:
        if (
            identifier not in claim.evidence_ids
            or fact["subject"] != claim.subject
            or fact["metric"] != claim.metric
        ):
            continue
        value = claim.value.value
        if isinstance(value, Quantity):
            target = Quantity.model_validate(fact["value"])
            if math.isclose(
                value.to(target.unit).value, target.value, rel_tol=1e-12, abs_tol=1e-12
            ):
                return
        elif isinstance(value, QuantityRange):
            target = QuantityRange.model_validate(fact["value"])
            converted = value.to(target.unit)
            if math.isclose(
                converted.lower, target.lower, rel_tol=1e-12, abs_tol=1e-12
            ) and math.isclose(converted.upper, target.upper, rel_tol=1e-12, abs_tol=1e-12):
                return
        elif value == fact["value"]:
            return
    raise ValueError("claim differs from assigned structured evidence")


def receive_bundle(service: ProjectService, command, request_body, messages):
    """Store valid per-role drafts; preserve partial results and explicit gaps.

    A command maps the coordinator Run once. Child Briefs are covered by its
    immutable request fingerprint and native call IDs, not fictitious Gateway
    Runs or three conflicting copies of the parent upstream Run mapping.
    """
    parent = command.link.binding
    if request_hash(request_body) != command.intent.request_sha256:
        raise ValueError("bundle request differs from persisted command")
    assignments = load_assignments(request_body["input"]["mis_required_assignments"])
    if any(a.brief.project_id != parent.thread.project_id for a in assignments.values()):
        raise ValueError("bundle project differs from command")
    anchor = next((a for a in assignments.values() if a.brief.id == parent.thread.task_id), None)
    if anchor is None:
        raise ValueError("coordinator command anchor is absent")
    from mis.adapters.task_bridge import brief_hash

    if brief_hash(anchor.brief) != command.intent.brief_sha256:
        raise ValueError("coordinator anchor snapshot differs")
    last = next((m for m in reversed(messages) if m.get("type") == "ai"), {})
    execution = execution_report(messages, lead_final=complete_summary(last.get("content", "")))
    calls = {
        c["id"]: c["args"]["subagent_type"]
        for m in messages
        if m.get("type") == "ai"
        for c in m.get("tool_calls", [])
        if c.get("name") == "task"
    }
    results = {
        m["tool_call_id"]: m
        for m in messages
        if m.get("type") == "tool" and m.get("tool_call_id") in calls
    }
    outcomes = {}
    for role, assignment in assignments.items():
        if execution["roles"][role] != "completed":
            outcomes[role] = {
                "status": execution["roles"][role],
                "gap": "native_result_not_completed",
            }
            continue
        try:
            identifier = next(i for i, r in calls.items() if r == role)
            message = results[identifier]
            receipt = (message.get("additional_kwargs") or {}).get("deerflow_tool_receipt") or {}
            if (
                receipt.get("tool_call_id") != identifier
                or receipt.get("tool_name") != "task"
                or receipt.get("status") != "success"
            ):
                raise ValueError("native tool receipt mismatch")
            value = result_json(message)
            brief = service.get(AgentTaskBrief, assignment.brief.id)
            if brief != assignment.brief or brief.status == "stale":
                raise ValueError("brief snapshot changed")
            project = service.get(InstrumentProject, brief.project_id)
            if project.current_baseline_version != brief.baseline_version:
                raise ValueError("baseline is no longer current")
            if value.get("role") != role or value.get("task_id") != brief.id:
                raise ValueError("Specialist payload scope mismatch")
            for expected in assignment.evidence:
                if service.get(Evidence, expected.id) != expected:
                    raise ValueError("evidence snapshot changed")
            claims = []
            for index, raw in enumerate(value["claims"]):
                claim = Claim.model_validate({**raw, "claim_id": f"{brief.id}-claim-{index}"})
                if not set(claim.evidence_ids) <= {e.id for e in assignment.evidence}:
                    raise ValueError("unassigned evidence citation")
                _structured_support(claim, assignment.evidence)
                claims.append(claim)
            subjects = dict.fromkeys(c.subject for c in claims)
            candidate = AgentArtifact(
                id=stable_artifact_id(parent.run_id, brief.id),
                project_id=brief.project_id,
                brief_id=brief.id,
                artifact_type=role,
                requirement_refs=brief.requirement_refs,
                claims=tuple(claims),
                candidates=tuple(
                    Candidate(
                        subject=s, claim_ids=tuple(c.claim_id for c in claims if c.subject == s)
                    )
                    for s in subjects
                ),
                produced_by=RunRef(
                    run_id=parent.run_id, actor=role, model="gpt-6-luna", prompt_version="p2-0e-1"
                ),
            )
            candidate = validate_artifact_candidate(
                candidate.model_dump(mode="json"), brief, parent.run_id
            )
            baseline = service.baseline(brief.project_id, brief.baseline_version)
            scoped = baseline.model_copy(
                update={
                    "items": tuple(i for i in baseline.items if i.key in brief.requirement_refs)
                }
            )
            values = {
                i.key: tuple(c.value for c in claims if c.metric == i.metric) for i in scoped.items
            }
            evaluation = evaluate(scoped, values)
            if evaluation.verdict != "pass":
                outcomes[role] = {
                    "status": "failed",
                    "gap": "hard_constraints_" + evaluation.verdict,
                    "checks": evaluation.model_dump(mode="json"),
                }
                continue
            with service.session.begin_nested():
                stored = service.add(candidate)
            outcomes[role] = {
                "status": "stored_draft",
                "artifact_id": stored.id,
                "native_call_id": identifier,
                "rule_verdict": evaluation.verdict,
            }
        except (ValueError, KeyError, TypeError, StopIteration):
            outcomes[role] = {
                "status": "failed",
                "gap": "schema_scope_evidence_or_conflict_rejected",
            }
    complete = execution["status"] == "completed" and all(
        o["status"] == "stored_draft" for o in outcomes.values()
    )
    status = (
        "completed"
        if complete
        else "partial"
        if any(o["status"] == "stored_draft" for o in outcomes.values())
        else "failed"
    )
    return {"status": status, "execution": execution, "roles": outcomes, "adoption": "unreviewed"}
