"""Run python -m mis.schemas.export [--check] to maintain checked-in JSON Schema."""

import argparse
import json
from pathlib import Path

from mis.rules.compare import CheckResult, RamanContext
from mis.rules.evaluate import Evaluation
from mis.schemas.artifacts import AgentArtifact, Claim
from mis.schemas.evidence import Evidence
from mis.schemas.impact import ImpactReport
from mis.schemas.plan import InstrumentPlan
from mis.schemas.project import InstrumentProject
from mis.schemas.provenance import RunRef
from mis.schemas.questions import UserCorrection, UserQuestion
from mis.schemas.requirements import RequirementBaseline, RequirementItem
from mis.schemas.tasks import AgentTaskBrief
from mis.schemas.testing import TestResult
from mis.schemas.traceability import ClaimTrace
from mis.schemas.values import Known, Quantity, QuantityRange, Unknown

RECORD_MODELS = (
    InstrumentProject,
    RequirementBaseline,
    AgentTaskBrief,
    Evidence,
    AgentArtifact,
    InstrumentPlan,
    UserQuestion,
    UserCorrection,
    TestResult,
)
MODELS = (
    *RECORD_MODELS,
    Claim,
    RunRef,
    RequirementItem,
    Known,
    Unknown,
    Quantity,
    QuantityRange,
    CheckResult,
    RamanContext,
    Evaluation,
    ImpactReport,
    ClaimTrace,
)


def export_schemas(destination: Path = Path("docs/schemas"), *, check: bool = False):
    if not check:
        destination.mkdir(parents=True, exist_ok=True)
    for model in MODELS:
        path = destination / f"{model.__name__}.json"
        content = json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n"
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                raise ValueError(f"JSON Schema out of date: {path}")
        else:
            path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    export_schemas(check=parser.parse_args().check)
