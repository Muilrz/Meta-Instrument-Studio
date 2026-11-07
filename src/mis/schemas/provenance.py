from typing import Literal

from pydantic import Field

from mis.schemas.base import Model, Text


class RunRef(Model):
    run_id: Text
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    actor: Literal["copilot", "lab", "research", "procurement", "rule_engine", "user"]
    model: Text | None = None
    skill_versions: dict[str, str] = Field(default_factory=dict)
    prompt_version: Text | None = None
