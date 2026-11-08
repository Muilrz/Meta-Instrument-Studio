from datetime import datetime
from typing import Literal

from pydantic import Field

from mis.schemas.base import Model, Text, now

Status = Literal["draft", "accepted", "rejected", "stale"]


class StatusChange(Model):
    status: Status
    reason: Text
    trigger_id: Text
    created_at: datetime = Field(default_factory=now)
