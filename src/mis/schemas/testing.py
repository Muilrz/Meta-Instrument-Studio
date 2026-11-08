from typing import Literal

from pydantic import Field, model_validator

from mis.ids import EvidenceId, ProjectId, new_id
from mis.schemas.base import Model, Text
from mis.schemas.values import SpecValue, Unknown


class TestResult(Model):
    __test__ = False
    id: Text = Field(default_factory=lambda: new_id("tst"))
    project_id: ProjectId
    requirement_key: Text
    plan_version: int = Field(ge=1)
    measured: SpecValue
    verdict: Literal["pass", "fail", "unknown"]
    evidence_ids: tuple[EvidenceId, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unknown_verdict(self):
        if isinstance(self.measured, Unknown) and self.verdict != "unknown":
            raise ValueError("unknown measurement requires unknown verdict")
        return self
