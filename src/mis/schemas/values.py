from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from mis.schemas.base import Model, Text
from mis.units import convert, validate_unit


class Quantity(Model):
    value: float
    unit: Text

    _unit = field_validator("unit")(validate_unit)

    def to(self, unit: str) -> "Quantity":
        return Quantity(value=convert(self.value, self.unit, unit), unit=unit)


class QuantityRange(Model):
    lower: float
    upper: float
    unit: Text

    _unit = field_validator("unit")(validate_unit)

    @model_validator(mode="after")
    def ordered(self):
        if self.lower > self.upper:
            raise ValueError("range lower must not exceed upper")
        return self

    def to(self, unit: str) -> "QuantityRange":
        return QuantityRange(
            lower=convert(self.lower, self.unit, unit),
            upper=convert(self.upper, self.unit, unit),
            unit=unit,
        )


class Known(Model):
    kind: Literal["known"] = "known"
    value: Quantity | QuantityRange | Text
    evidence_ids: tuple[Text, ...] = Field(min_length=1)


class Unknown(Model):
    kind: Literal["unknown"] = "unknown"
    reason: Text
    evidence_ids: tuple[Text, ...] = ()


SpecValue = Annotated[Known | Unknown, Field(discriminator="kind")]
