from typing import Literal

from mis.schemas.artifacts import AgentArtifact
from mis.schemas.base import Model
from mis.schemas.evidence import Evidence
from mis.schemas.plan import InstrumentPlan
from mis.schemas.project import InstrumentProject
from mis.schemas.questions import UserCorrection, UserQuestion
from mis.schemas.requirements import RequirementBaseline
from mis.schemas.tasks import AgentTaskBrief
from mis.schemas.testing import TestResult


class ProjectBackup(Model):
    """Logical business backup. Contains no runtime or database credentials."""

    format_version: Literal["1"] = "1"
    projects: tuple[InstrumentProject, ...] = ()
    baselines: tuple[RequirementBaseline, ...] = ()
    briefs: tuple[AgentTaskBrief, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    artifacts: tuple[AgentArtifact, ...] = ()
    plans: tuple[InstrumentPlan, ...] = ()
    questions: tuple[UserQuestion, ...] = ()
    corrections: tuple[UserCorrection, ...] = ()
    test_results: tuple[TestResult, ...] = ()
