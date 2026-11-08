from typing import Literal

from pydantic import Field

from mis.ids import ArtifactId, PlanId, ProjectId, new_id
from mis.schemas.base import Model, Text
from mis.schemas.provenance import RunRef
from mis.schemas.status import Status, StatusChange


class ClaimRef(Model):
    artifact_id: ArtifactId
    claim_id: Text


class BomEntry(Model):
    subject: Text
    quantity: int = Field(default=1, ge=1)
    claim_refs: tuple[ClaimRef, ...] = Field(min_length=1)


class PlanConclusion(Model):
    statement: Text
    claim_refs: tuple[ClaimRef, ...] = Field(min_length=1)


class InstrumentPlan(Model):
    id: PlanId = Field(default_factory=lambda: new_id("pln"))
    project_id: ProjectId
    version: int = Field(ge=1)
    baseline_version: int = Field(ge=1)
    artifact_ids: tuple[ArtifactId, ...] = Field(min_length=1)
    modules: tuple[PlanConclusion, ...] = ()
    bom: tuple[BomEntry, ...] = Field(min_length=1)
    rationale: tuple[PlanConclusion, ...] = Field(min_length=1)
    risks: tuple[Text, ...] = ()
    stage2_tasks: tuple[Text, ...] = ()
    check_summary: dict[str, Literal["pass", "fail", "unknown"]]
    produced_by: RunRef
    status: Status = "draft"
    status_history: tuple[StatusChange, ...] = ()
