from pydantic import Field, model_validator

from mis.ids import ArtifactId, BriefId, ProjectId, new_id
from mis.schemas.base import Model, Text
from mis.schemas.metrics import ENUM_METRICS, METRIC_UNITS, check_dimension
from mis.schemas.provenance import RunRef
from mis.schemas.status import Status, StatusChange
from mis.schemas.values import Known, Quantity, QuantityRange, SpecValue


class Claim(Model):
    claim_id: Text = Field(default_factory=lambda: new_id("clm"))
    statement: Text
    subject: Text
    metric: Text
    value: SpecValue

    @property
    def evidence_ids(self):
        return self.value.evidence_ids

    @model_validator(mode="after")
    def dimension(self):
        if isinstance(self.value, Known):
            value = self.value.value
            if isinstance(value, (Quantity, QuantityRange)):
                if self.metric in ENUM_METRICS:
                    raise ValueError("enum metric requires text")
                check_dimension(self.metric, value.unit, domain_resolution=True)
            elif self.metric in METRIC_UNITS:
                raise ValueError("numeric metric requires quantity")
        return self


class Candidate(Model):
    subject: Text
    claim_ids: tuple[Text, ...] = Field(min_length=1)


class AgentArtifact(Model):
    id: ArtifactId = Field(default_factory=lambda: new_id("art"))
    project_id: ProjectId
    brief_id: BriefId
    artifact_type: Text
    requirement_refs: tuple[Text, ...] = Field(min_length=1)
    candidates: tuple[Candidate, ...] = ()
    claims: tuple[Claim, ...] = Field(min_length=1)
    assumptions: tuple[Text, ...] = ()
    open_questions: tuple[Text, ...] = ()
    produced_by: RunRef
    status: Status = "draft"
    status_history: tuple[StatusChange, ...] = ()

    @model_validator(mode="after")
    def candidates_resolve(self):
        claims = {c.claim_id: c for c in self.claims}
        if len(claims) != len(self.claims):
            raise ValueError("duplicate claim id")
        for candidate in self.candidates:
            if any(
                cid not in claims or claims[cid].subject != candidate.subject
                for cid in candidate.claim_ids
            ):
                raise ValueError("candidate claim reference mismatch")
        return self
