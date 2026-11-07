from pydantic import Field, model_validator

from mis.ids import ArtifactId, BriefId, PlanId, ProjectId
from mis.schemas.base import Model, Text


class ImpactReport(Model):
    project_id: ProjectId
    from_version: int = Field(ge=1)
    to_version: int = Field(ge=1)
    changed_keys: tuple[Text, ...]
    brief_ids: tuple[BriefId, ...]
    artifact_ids: tuple[ArtifactId, ...]
    plan_ids: tuple[PlanId, ...]

    @model_validator(mode="after")
    def version_order(self):
        if self.to_version <= self.from_version:
            raise ValueError("impact requires a newer baseline")
        return self

    @property
    def reason(self):
        return (
            f"需求 v{self.from_version} → v{self.to_version}，{', '.join(self.changed_keys)} 变更"
        )
