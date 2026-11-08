import json

import pytest
from pydantic import ValidationError

from mis.schemas.export import MODELS, export_schemas
from mis.schemas.values import Unknown


def test_schemas_match_exports(tmp_path):
    export_schemas(tmp_path)
    for model in MODELS:
        assert (
            json.loads((tmp_path / f"{model.__name__}.json").read_text())
            == model.model_json_schema()
        )


def test_every_record_roundtrips_and_rejects_extra_fields(records):
    for record in records:
        assert type(record).model_validate_json(record.model_dump_json()) == record
        with pytest.raises(ValidationError):
            type(record).model_validate({**record.model_dump(), "unexpected": True})


@pytest.mark.parametrize(
    "index,changes",
    [
        (0, {"name": ""}),
        (1, {"items": []}),
        (2, {"baseline_version": 0}),
        (3, {"excerpt": ""}),
        (4, {"claims": []}),
        (5, {"rationale": []}),
        (6, {"status": "answered"}),
        (7, {"reason": ""}),
        (8, {"verdict": "maybe"}),
        (8, {"measured": Unknown(reason="not reported"), "verdict": "pass"}),
    ],
)
def test_business_record_invalid_examples(records, index, changes):
    record = records[index]
    with pytest.raises(ValidationError):
        type(record).model_validate({**record.model_dump(), **changes})


def test_run_ref_and_requirement_contracts():
    from mis.schemas.provenance import RunRef
    from mis.schemas.requirements import RequirementItem

    assert RunRef.model_validate_json(RunRef(run_id="r1", actor="user").model_dump_json())
    with pytest.raises(ValidationError):
        RunRef(run_id="r1", actor="user", trace_id="not-an-otel-trace-id")
    with pytest.raises(ValidationError):
        RequirementItem(
            key="R01",
            name="wavelength",
            metric="laser.center_wavelength",
            comparator="range",
            lower=800,
            upper=785,
            unit="nm",
            verification="measure",
        )


def test_metric_dimensions_and_brief_parameters(records):
    from mis.schemas.artifacts import Claim
    from mis.schemas.requirements import RequirementItem
    from mis.schemas.tasks import AgentTaskBrief, OpenParam, SpecifiedParam
    from mis.schemas.values import Known, Quantity

    with pytest.raises(ValidationError):
        RequirementItem(
            key="R04",
            name="power",
            metric="laser.max_power",
            comparator="min",
            lower=450,
            unit="nm",
            verification="measure",
        )
    with pytest.raises(ValidationError):
        Claim(
            statement="power",
            subject="LAS-A",
            metric="laser.max_power",
            value=Known(value=Quantity(value=1, unit="nm"), evidence_ids=("evd_source",)),
        )
    baseline = records[1]
    with pytest.raises(ValidationError):
        AgentTaskBrief(
            project_id=baseline.project_id,
            baseline_version=1,
            requirement_refs=("R04",),
            specialist="procurement",
            goal="select",
            specified_params=(
                SpecifiedParam(name="power", requirement_key="R04", target=baseline.items[0]),
            ),
            open_params=(OpenParam(name="power", unit="mW"),),
        )
