import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from mis.ids import new_id
from mis.project_service.repository import ProjectService
from mis.schemas.artifacts import AgentArtifact
from mis.schemas.evidence import Evidence
from mis.schemas.plan import InstrumentPlan
from mis.schemas.project import InstrumentProject
from mis.schemas.requirements import RequirementBaseline
from mis.schemas.values import Known, Quantity


def seed(service, records):
    for record in records[:7]:
        service.add(record)


def test_roundtrip_versions_run_query_and_delete(db_session, records):
    service = ProjectService(db_session)
    seed(service, records)
    for record in records[1:7]:
        assert service.get(type(record), record.id) == record
    assert service.get(InstrumentProject, records[0].id).current_plan_version == 1
    baseline = records[1]
    v2 = service.revise_baseline(baseline.project_id, items=baseline.items, change_note="review")
    assert v2.version == 2
    assert service.baseline(baseline.project_id, 1) == baseline
    assert service.get(InstrumentProject, records[0].id).current_baseline_version == 2
    assert {r.id for r in service.by_run("manual-run")} == {records[i].id for i in (3, 4, 5, 6)}
    empty = service.add(InstrumentProject(name="empty"))
    service.delete_project(empty.id)
    with pytest.raises(KeyError):
        service.get(InstrumentProject, empty.id)
    plan_v2 = service.revise_plan(records[5], risks=("reviewed",))
    assert plan_v2.version == 2
    assert service.plan(baseline.project_id, 1) == records[5]
    stale = service.set_status(
        AgentArtifact, records[4].id, "stale", reason="test revision", trigger_id=v2.id
    )
    assert stale.claims == records[4].claims
    assert stale.status_history[-1].reason == "test revision"
    with pytest.raises(ValueError):
        service.set_status(AgentArtifact, stale.id, "accepted", reason="invalid", trigger_id=v2.id)


def test_reject_missing_evidence_and_foreign_baseline_parameter(db_session, records):
    service = ProjectService(db_session)
    for record in records[:4]:
        service.add(record)
    artifact = records[4]
    claim = artifact.claims[0].model_copy(
        update={"value": Known(value=Quantity(value=500, unit="mW"), evidence_ids=("evd_missing",))}
    )
    with pytest.raises((KeyError, ValueError)):
        service.add(artifact.model_copy(update={"claims": (claim,)}))
    bad_brief = records[2].model_copy(
        update={
            "id": new_id("brf"),
            "requirement_refs": ("R99",),
        }
    )
    with pytest.raises(ValueError):
        service.add(bad_brief)
    foreign = service.add(InstrumentProject(name="other"))
    foreign_evidence = records[3].model_copy(update={"project_id": foreign.id})
    with pytest.raises(ValueError):
        service.add(foreign_evidence)  # existing ID cannot be overwritten or moved


@pytest.mark.parametrize(
    "model,index",
    [(Evidence, 3), (RequirementBaseline, 1), (AgentArtifact, 4), (InstrumentPlan, 5)],
)
def test_database_rejects_immutable_writes(db_session, records, model, index):
    service = ProjectService(db_session)
    seed(service, records)
    table = service.table(model)
    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.execute(
            table.update()
            .where(table.c.id == records[index].id)
            .values(body={**records[index].model_dump(mode="json"), "illegal_change": True})
        )
    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.execute(table.delete().where(table.c.id == records[index].id))


def test_runtime_read_only_and_app_immutability(db_session, records):
    service = ProjectService(db_session)
    seed(service, records)
    with db_session.begin_nested():
        db_session.execute(text("SET LOCAL ROLE mis_runtime"))
        assert db_session.scalar(text("SELECT count(*) FROM mis.projects")) >= 1
        with pytest.raises(DBAPIError), db_session.begin_nested():
            db_session.execute(text("UPDATE mis.projects SET body = body"))
        db_session.execute(text("RESET ROLE"))
    with db_session.begin_nested():
        db_session.execute(text("SET LOCAL ROLE mis_app"))
        with pytest.raises(DBAPIError), db_session.begin_nested():
            db_session.execute(text("DELETE FROM mis.evidence"))
        db_session.execute(text("RESET ROLE"))
