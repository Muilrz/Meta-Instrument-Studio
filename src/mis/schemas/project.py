from datetime import datetime
from typing import Literal

from pydantic import Field

from mis.ids import ProjectId, new_id
from mis.schemas.base import Model, Text, now


class InstrumentProject(Model):
    id: ProjectId = Field(default_factory=lambda: new_id("prj"))
    name: Text
    kind: Literal["normal", "benchmark"] = "normal"
    members: tuple[Text, ...] = ()
    knowledge_scope: tuple[Text, ...] = ()
    current_baseline_version: int | None = Field(default=None, ge=1)
    current_plan_version: int | None = Field(default=None, ge=1)
    created_at: datetime = Field(default_factory=now)
