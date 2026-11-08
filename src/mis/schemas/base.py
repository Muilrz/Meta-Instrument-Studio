from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def now() -> datetime:
    return datetime.now(UTC)
