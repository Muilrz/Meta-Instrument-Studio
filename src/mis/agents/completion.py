"""Fixed MIS role completeness policy; execution stays in native task/delegation."""

from dataclasses import dataclass

from mis.agents.profiles import SPECIALISTS
from mis.schemas.evidence import Evidence
from mis.schemas.tasks import AgentTaskBrief


@dataclass(frozen=True)
class AssignedTask:
    brief: AgentTaskBrief
    evidence: tuple[Evidence, ...]

    def __post_init__(self):
        if self.brief.status == "stale" or not self.evidence:
            raise ValueError("assigned brief must be current and have authorized evidence")
        if self.brief.budget.model_calls != 1:
            raise ValueError("fixed Specialist assignment requires one allocated model call")
        if any(e.project_id != self.brief.project_id for e in self.evidence):
            raise ValueError("cross-project evidence assignment")

    def dump(self):
        return {
            "brief": self.brief.model_dump(mode="json"),
            "evidence": [e.model_dump(mode="json") for e in self.evidence],
        }

    @classmethod
    def load(cls, value):
        return cls(
            AgentTaskBrief.model_validate(value["brief"]),
            tuple(Evidence.model_validate(e) for e in value["evidence"]),
        )

    def prompt(self):
        from mis.agents.completion_policy import assignment_prompt

        return assignment_prompt(self.dump())


def load_assignments(values) -> dict[str, AssignedTask]:
    assignments = [AssignedTask.load(v) for v in values]
    by_role = {a.brief.specialist: a for a in assignments}
    if set(by_role) != set(SPECIALISTS) or len(assignments) != len(SPECIALISTS):
        raise ValueError("exactly one assigned brief per required Specialist")
    if len({a.brief.id for a in assignments}) != 3:
        raise ValueError("assigned brief IDs must be distinct")
    if len({(a.brief.project_id, a.brief.baseline_version) for a in assignments}) != 1:
        raise ValueError("bundle project/baseline mismatch")
    return by_role
