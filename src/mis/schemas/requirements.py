from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from mis.ids import BaselineId, ProjectId, new_id
from mis.schemas.base import Model, Text, now
from mis.schemas.metrics import ENUM_METRICS, METRIC_UNITS, check_dimension
from mis.schemas.values import Quantity
from mis.units import validate_unit


class RequirementItem(Model):
    key: Text
    name: Text
    metric: Text
    comparator: Literal["min", "max", "range", "covers", "enum"]
    lower: float | None = None
    upper: float | None = None
    allowed: tuple[Text, ...] = ()
    unit: Text | None = None
    priority: Literal["must", "should"] = "must"
    verification: Text

    @model_validator(mode="after")
    def contract(self):
        if self.comparator == "enum":
            if self.metric in METRIC_UNITS:
                raise ValueError("numeric metric requires a numeric comparator")
            if not self.allowed or self.unit or self.lower is not None or self.upper is not None:
                raise ValueError("enum needs allowed values only")
        else:
            if self.metric in ENUM_METRICS:
                raise ValueError("enumeration metric requires enum comparator")
            if self.unit is None or self.allowed:
                raise ValueError("numeric comparison requires unit and no enumeration")
            validate_unit(self.unit)
            check_dimension(self.metric, self.unit)
            if self.comparator in ("min", "range", "covers") and self.lower is None:
                raise ValueError("lower bound required")
            if self.comparator in ("max", "range", "covers") and self.upper is None:
                raise ValueError("upper bound required")
            if self.comparator == "min" and self.upper is not None:
                raise ValueError("min accepts lower bound only")
            if self.comparator == "max" and self.lower is not None:
                raise ValueError("max accepts upper bound only")
            if self.lower is not None and self.upper is not None and self.lower > self.upper:
                raise ValueError("reversed bounds")
        return self


class RequirementBaseline(Model):
    id: BaselineId = Field(default_factory=lambda: new_id("req"))
    project_id: ProjectId
    version: int = Field(ge=1)
    items: tuple[RequirementItem, ...] = Field(min_length=1)
    budget: Quantity | None = None
    created_at: datetime = Field(default_factory=now)
    change_note: Text

    @field_validator("items")
    @classmethod
    def unique_keys(cls, items):
        if len({item.key for item in items}) != len(items):
            raise ValueError("duplicate requirement key")
        return items

    @model_validator(mode="after")
    def budget_matches(self):
        if self.budget:
            amount = self.budget.to("CNY").value
            if amount < 0:
                raise ValueError("negative budget")
            for item in self.items:
                if item.metric == "project.bom_total":
                    if (
                        item.comparator != "max"
                        or amount != Quantity(value=item.upper, unit=item.unit).to("CNY").value
                    ):
                        raise ValueError("budget must match BOM requirement")
        return self
