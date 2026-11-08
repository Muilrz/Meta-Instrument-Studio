import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from mis.ids import new_id
from mis.project_service.impact import analyze
from mis.project_service.repository import ProjectService
from mis.schemas.artifacts import AgentArtifact
from mis.schemas.base import now
from mis.schemas.impact import ImpactReport
from mis.schemas.plan import InstrumentPlan
from mis.schemas.questions import UserQuestion
from mis.schemas.tasks import AgentTaskBrief


def test_new_records_cannot_reuse_stale_dependencies(db_session, records):
    service = ProjectService(db_session)
    for record in records[:7]:
        service.add(record)
    service.set_status(AgentTaskBrief, records[2].id, "stale", reason="changed", trigger_id="test")
    new_artifact = records[4].model_copy(update={"id": new_id("art")})
    for candidate in (new_artifact, new_artifact.model_copy(update={"status": "stale"})):
        with pytest.raises(ValueError, match="stale brief"):
            service.add(candidate)
    service.set_status(AgentArtifact, records[4].id, "stale", reason="changed", trigger_id="test")
    with pytest.raises(ValueError, match="stale artifact"):
        service.revise_plan(records[5], risks=("new plan must not reuse stale content",))
    assert service.get(InstrumentPlan, records[5].id) == records[5]
    assert service.get(AgentArtifact, records[4].id).claims == records[4].claims


def test_impact_requires_adjacent_versions(db_session, records):
    service = ProjectService(db_session)
    service.add(records[0])
    service.add(records[1])
    for version in (2, 3):
        service.revise_baseline(records[0].id, items=records[1].items, change_note=f"v{version}")
    with pytest.raises(ValueError, match="adjacent"):
        analyze(service, records[0].id, 1, 3)
    with pytest.raises(ValidationError, match="adjacent"):
        ImpactReport(
            project_id=records[0].id,
            from_version=1,
            to_version=3,
            changed_keys=(),
            brief_ids=(),
            artifact_ids=(),
            plan_ids=(),
        )


def test_question_database_guards_allow_answer_but_reject_rewrites(db_session, records):
    service = ProjectService(db_session)
    for index in (0, 3, 6):
        service.add(records[index])
    question = records[6]
    table = service.table(UserQuestion)
    db_session.execute(text("SET LOCAL ROLE mis_app"))
    for changes in (
        {"context": "rewritten"},
        {
            "status": "answered",
            "answer": "forged",
            "answered_at": now().isoformat(),
            "answer_evidence_id": records[3].id,
        },
    ):
        with pytest.raises(DBAPIError), db_session.begin_nested():
            db_session.execute(
                table.update()
                .where(table.c.id == question.id)
                .values(
                    body={**question.model_dump(mode="json"), **changes},
                    status=changes.get("status", "open"),
                )
            )
    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.execute(table.delete().where(table.c.id == question.id))
    answered = service.answer_question(question.id, answer="Python", run=records[3].retrieved_by)
    assert answered.status == "answered"
    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.execute(
            table.update()
            .where(table.c.id == question.id)
            .values(body={**answered.model_dump(mode="json"), "answer": "C"})
        )
    assert service.get(UserQuestion, question.id) == answered
    db_session.execute(text("RESET ROLE"))
    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.execute(text("TRUNCATE mis.questions"))


def test_question_cancel_is_terminal(db_session, records):
    service = ProjectService(db_session)
    service.add(records[0])
    question = service.add(records[6])
    table = service.table(UserQuestion)
    db_session.execute(text("SET LOCAL ROLE mis_app"))
    cancelled = question.model_copy(update={"status": "cancelled"})
    db_session.execute(
        table.update()
        .where(table.c.id == question.id)
        .values(body=cancelled.model_dump(mode="json"), status="cancelled")
    )
    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.execute(
            table.update()
            .where(table.c.id == question.id)
            .values(body=question.model_dump(mode="json"), status="open")
        )
    assert service.get(UserQuestion, question.id) == cancelled
