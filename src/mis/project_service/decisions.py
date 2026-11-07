from mis.project_service.repository import ProjectService
from mis.schemas.artifacts import AgentArtifact
from mis.schemas.base import now
from mis.schemas.evidence import Evidence
from mis.schemas.provenance import RunRef
from mis.schemas.questions import UserCorrection, UserQuestion
from mis.schemas.values import Known, Quantity, QuantityRange, Unknown


def answer_question(service: ProjectService, identifier: str, *, answer: str, run: RunRef):
    with service.session.begin_nested():
        question = service.get(UserQuestion, identifier)
        service._project_lock(question.project_id)
        question = service.get(UserQuestion, identifier)
        if run.actor != "user" or run.run_id != question.run_id:
            raise ValueError("answer requires the question run and a user actor")
        if question.status == "answered" and question.answer == answer:
            return question
        if question.status != "open":
            raise ValueError("question is no longer open")
        evidence = service.add(
            Evidence(
                project_id=question.project_id,
                source_type="user_decision",
                locator=question.id,
                excerpt=answer,
                page_or_anchor="answer",
                source_version="1",
                retrieved_by=run,
            )
        )
        updated = UserQuestion.model_validate(
            {
                **question.model_dump(),
                "answer": answer,
                "status": "answered",
                "answered_at": now(),
                "answer_evidence_id": evidence.id,
            }
        )
        return service._replace_mutable(updated)


def correct_claim(
    service: ProjectService,
    artifact_id: str,
    claim_id: str,
    *,
    corrected_value: Quantity | QuantityRange | str | Unknown,
    reason: str,
    corrected_by: str,
    run: RunRef,
):
    if run.actor != "user":
        raise ValueError("correction requires a user actor")
    with service.session.begin_nested():
        artifact = service.get(AgentArtifact, artifact_id)
        service._project_lock(artifact.project_id)
        claim = next((c for c in artifact.claims if c.claim_id == claim_id), None)
        if claim is None:
            raise KeyError("claim not found")
        excerpt = f"{corrected_by}: {reason}; corrected value: {corrected_value}"
        evidence = service.add(
            Evidence(
                project_id=artifact.project_id,
                source_type="user_decision",
                locator=f"{artifact_id}/{claim_id}",
                excerpt=excerpt,
                page_or_anchor="correction",
                source_version="1",
                retrieved_by=run,
            )
        )
        value = (
            corrected_value.model_copy(
                update={"evidence_ids": (*corrected_value.evidence_ids, evidence.id)}
            )
            if isinstance(corrected_value, Unknown)
            else (Known(value=corrected_value, evidence_ids=(evidence.id,)))
        )
        # Reuse Claim validation to reject dimensions inconsistent with the corrected metric.
        type(claim).model_validate({**claim.model_dump(), "value": value})
        return service.add(
            UserCorrection(
                project_id=artifact.project_id,
                artifact_id=artifact_id,
                claim_id=claim_id,
                original_value=claim.value,
                corrected_value=value,
                reason=reason,
                evidence_id=evidence.id,
                corrected_by=corrected_by,
            )
        )
