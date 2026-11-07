from typing import Literal

from pydantic import Field, model_validator

from mis.ids import BriefId, ProjectId, new_id
from mis.schemas.base import Model, Text
from mis.schemas.requirements import RequirementItem
from mis.schemas.status import Status, StatusChange
from mis.units import validate_unit


class SpecifiedParam(Model):
    name: Text
    requirement_key: Text
    target: RequirementItem

    @model_validator(mode="after")
    def matching_key(self):
        if self.target.key != self.requirement_key:
            raise ValueError("specified parameter target key mismatch")
        return self


class OpenParam(Model):
    name: Text
    unit: Text

    @model_validator(mode="after")
    def unit_valid(self):
        validate_unit(self.unit)
        return self


class TaskBudget(Model):
    seconds: float = Field(default=300, gt=0)
    searches: int = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0)


class Usage(Model):
    seconds: float = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    searches: int = Field(default=0, ge=0)
    cost_cny: float = Field(default=0, ge=0)


class AgentTaskBrief(Model):
    id: BriefId = Field(default_factory=lambda: new_id("brf"))
    project_id: ProjectId
    baseline_version: int = Field(ge=1)
    requirement_refs: tuple[Text, ...] = Field(min_length=1)
    specialist: Literal["lab", "research", "procurement"]
    goal: Text
    specified_params: tuple[SpecifiedParam, ...] = ()
    open_params: tuple[OpenParam, ...] = ()
    constraints: tuple[Text, ...] = ()
    acceptance: tuple[Text, ...] = ()
    budget: TaskBudget = Field(default_factory=TaskBudget)
    usage: Usage = Field(default_factory=Usage)
    status: Status = "draft"
    status_history: tuple[StatusChange, ...] = ()

    @model_validator(mode="after")
    def parameters(self):
        names = [p.name for p in (*self.specified_params, *self.open_params)]
        if len(names) != len(set(names)):
            raise ValueError("duplicate or overlapping parameter names")
        if any(p.requirement_key not in self.requirement_refs for p in self.specified_params):
            raise ValueError("specified parameter missing requirement reference")
        return self
