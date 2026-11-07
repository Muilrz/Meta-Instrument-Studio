import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from mis.project_service.db import ROOT, engine_for
from mis.schemas.artifacts import AgentArtifact, Claim
from mis.schemas.evidence import Evidence
from mis.schemas.plan import BomEntry, ClaimRef, InstrumentPlan, PlanConclusion
from mis.schemas.project import InstrumentProject
from mis.schemas.provenance import RunRef
from mis.schemas.questions import UserCorrection, UserQuestion
from mis.schemas.requirements import RequirementBaseline, RequirementItem
from mis.schemas.tasks import AgentTaskBrief
from mis.schemas.testing import TestResult
from mis.schemas.values import Known, Quantity, Unknown


@pytest.fixture(scope="session")
def db_engine():
    failure = None
    try:
        engine = engine_for(test=True)
        with engine.begin() as connection:
            connection.exec_driver_sql((ROOT / "db/init.sql").read_text(encoding="utf-8"))
            config = Config(str(ROOT / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    except Exception as exc:
        failure = type(exc).__name__
    if failure:
        pytest.fail(
            f"Test database setup failed ({failure}); configure "
            "MIS_TEST_DATABASE_URL for an independent Neon test branch or Docker. "
            "Connection details suppressed.",
            pytrace=False,
        )
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    with db_engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()


@pytest.fixture
def records():
    project = InstrumentProject(name="Raman")
    run = RunRef(run_id="manual-run", actor="user")
    item = RequirementItem(
        key="R04",
        name="power",
        metric="laser.max_power",
        comparator="min",
        lower=450,
        unit="mW",
        verification="measure",
    )
    baseline = RequirementBaseline(
        project_id=project.id, version=1, items=(item,), change_note="initial"
    )
    brief = AgentTaskBrief(
        project_id=project.id,
        baseline_version=1,
        requirement_refs=("R04",),
        specialist="procurement",
        goal="select laser",
    )
    evidence = Evidence(
        project_id=project.id,
        source_type="document",
        locator="LAS-A.md",
        excerpt="500 mW",
        page_or_anchor="power",
        source_version="1",
        retrieved_by=run,
    )
    value = Known(value=Quantity(value=500, unit="mW"), evidence_ids=(evidence.id,))
    claim = Claim(statement="power", subject="LAS-A", metric="laser.max_power", value=value)
    artifact = AgentArtifact(
        project_id=project.id,
        brief_id=brief.id,
        artifact_type="procurement",
        requirement_refs=("R04",),
        claims=(claim,),
        produced_by=run,
    )
    ref = ClaimRef(artifact_id=artifact.id, claim_id=claim.claim_id)
    plan = InstrumentPlan(
        project_id=project.id,
        version=1,
        baseline_version=1,
        artifact_ids=(artifact.id,),
        bom=(BomEntry(subject="LAS-A", claim_refs=(ref,)),),
        rationale=(PlanConclusion(statement="power", claim_refs=(ref,)),),
        check_summary={"R04": "pass"},
        produced_by=run,
    )
    question = UserQuestion(
        project_id=project.id, run_id=run.run_id, question="Which SDK?", context="preference"
    )
    correction = UserCorrection(
        project_id=project.id,
        artifact_id=artifact.id,
        claim_id=claim.claim_id,
        original_value=value,
        corrected_value=Unknown(reason="recheck"),
        reason="recheck",
        evidence_id=evidence.id,
        corrected_by="owner",
    )
    result = TestResult(
        project_id=project.id,
        requirement_key="R04",
        plan_version=1,
        measured=value,
        verdict="pass",
        evidence_ids=(evidence.id,),
    )
    return project, baseline, brief, evidence, artifact, plan, question, correction, result
