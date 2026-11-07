from typing import Literal

from pydantic import Field

from mis.ids import EvidenceId, ProjectId, new_id
from mis.schemas.base import Model, Text
from mis.schemas.values import SpecValue


class TestResult(Model):
    __test__ = False
    id: Text = Field(default_factory=lambda: new_id("tst"))
    project_id: ProjectId
    requirement_key: Text
    plan_version: int = Field(ge=1)
    measured: SpecValue
    verdict: Literal["pass", "fail", "unknown"]
    evidence_ids: tuple[EvidenceId, ...] = Field(min_length=1)
