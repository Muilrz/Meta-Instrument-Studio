from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from mis.ids import ArtifactId, BriefId, EvidenceId, ProjectId, new_id
from mis.schemas.base import Model, Text, now
from mis.schemas.values import SpecValue


class UserQuestion(Model):
    id: Text = Field(default_factory=lambda: new_id("que"))
    project_id: ProjectId
    run_id: Text
    brief_id: BriefId | None = None
    question: Text
    options: tuple[Text, ...] = ()
    context: Text
    answer: Text | None = None
    answered_at: datetime | None = None
    answer_evidence_id: EvidenceId | None = None
    status: Literal["open", "answered", "cancelled"] = "open"

    @model_validator(mode="after")
    def answer_contract(self):
        fields = (self.answer, self.answered_at, self.answer_evidence_id)
        if self.status == "answered" and not all(v is not None for v in fields):
            raise ValueError("answered question requires answer, time and evidence")
        if self.status != "answered" and any(v is not None for v in fields):
            raise ValueError("unanswered question cannot contain answer data")
        return self


class UserCorrection(Model):
    id: Text = Field(default_factory=lambda: new_id("cor"))
    project_id: ProjectId
    artifact_id: ArtifactId
    claim_id: Text
    original_value: SpecValue
    corrected_value: SpecValue
    reason: Text
    evidence_id: EvidenceId
    corrected_by: Text
    created_at: datetime = Field(default_factory=now)
