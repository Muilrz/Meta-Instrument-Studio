from datetime import date, datetime
from typing import Literal

from pydantic import Field, model_validator

from mis.ids import EvidenceId, ProjectId, new_id
from mis.schemas.base import Model, Text, now
from mis.schemas.provenance import RunRef


class PriceTier(Model):
    min_qty: int = Field(ge=1)
    unit_price: float = Field(ge=0)


class Quote(Model):
    currency: Literal["CNY", "USD"]
    price_tiers: tuple[PriceTier, ...] = Field(min_length=1)
    region: Text
    valid_until: date
    tax_included: bool


class FxRate(Model):
    source_currency: Literal["USD"]
    target_currency: Literal["CNY"] = "CNY"
    rate: float = Field(gt=0)
    as_of: date


class Evidence(Model):
    id: EvidenceId = Field(default_factory=lambda: new_id("evd"))
    project_id: ProjectId
    source_type: Literal["document", "web", "vendor_api", "fx_rate", "measurement", "user_decision"]
    locator: Text
    excerpt: Text
    page_or_anchor: Text
    retrieved_at: datetime = Field(default_factory=now)
    source_version: Text
    retrieved_by: RunRef
    tool_call_id: Text | None = None
    quote: Quote | None = None
    fx_rate: FxRate | None = None

    @model_validator(mode="after")
    def fx_contract(self):
        if (self.source_type == "fx_rate") != (self.fx_rate is not None):
            raise ValueError("fx_rate source requires structured FX rate exclusively")
        return self
