import pytest

from mis.ids import new_id
from mis.project_service.dump import dump_data, restore_data
from mis.project_service.impact import analyze, apply_impact
from mis.project_service.repository import ProjectService
from mis.schemas.evidence import Evidence
from mis.schemas.export import RECORD_MODELS
from mis.schemas.values import Quantity, Unknown


def test_all_business_objects_restore_without_runtime(db_session, records):
    service = ProjectService(db_session)
    seed = db_session.begin_nested()
    for record in records[:7]:
        service.add(record)
    service.revise_plan(records[5], risks=("revision retained",))
    service.answer_question(records[6].id, answer="Python SDK", run=records[3].retrieved_by)
    service.correct_claim(
        records[4].id,
        records[4].claims[0].claim_id,
        corrected_value=Quantity(value=400, unit="mW"),
        reason="corrected measured power",
        corrected_by="owner",
        run=records[3].retrieved_by,
    )
    service.add(
        records[8].model_copy(
            update={"measured": Unknown(reason="not measured yet"), "verdict": "unknown"}
        )
    )
    items = tuple(item.model_copy(update={"lower": 300}) for item in records[1].items)
    service.revise_baseline(records[0].id, items=items, change_note="lower power target")
    apply_impact(service, analyze(service, records[0].id, 1, 2))
    snapshot = dump_data(service)
    serialized = snapshot.model_dump_json()
    assert all(getattr(snapshot, service.table(model).name) for model in RECORD_MODELS)
    seed.rollback()  # empty restore target, without deleting immutable Evidence
    assert all(not service.list(model) for model in RECORD_MODELS)
    restore_data(service, serialized)
    assert dump_data(service) == snapshot
    with pytest.raises(ValueError):
        restore_data(service, serialized)  # never merge into an occupied target


def test_failed_restore_is_atomic(db_session, records):
    service = ProjectService(db_session)
    savepoint = db_session.begin_nested()
    for record in records[:7]:
        service.add(record)
    snapshot = dump_data(service)
    savepoint.rollback()
    bad_artifact = snapshot.artifacts[0]
    value = bad_artifact.claims[0].value.model_copy(update={"evidence_ids": (new_id("evd"),)})
    bad_claim = bad_artifact.claims[0].model_copy(update={"value": value})
    bad_artifact = bad_artifact.model_copy(update={"claims": (bad_claim,)})
    corrupt = snapshot.model_copy(update={"artifacts": (bad_artifact,)})
    with pytest.raises(KeyError):
        restore_data(service, corrupt.model_dump_json())
    assert not service.list(Evidence)
    assert all(not service.list(model) for model in RECORD_MODELS)
