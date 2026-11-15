"""MIS-side fixed business data, also callable offline by native SDK probes."""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))


def build():
    from mis.agents.completion import AssignedTask
    from mis.agents.profiles import SPECIALISTS
    from mis.schemas.evidence import Evidence
    from mis.schemas.project import InstrumentProject
    from mis.schemas.provenance import RunRef
    from mis.schemas.requirements import RequirementBaseline, RequirementItem
    from mis.schemas.tasks import AgentTaskBrief, SpecifiedParam, TaskBudget

    project = InstrumentProject(name="P2-0E fixed three-role fixture")
    target = RequirementItem(
        key="R04",
        name="power",
        metric="laser.max_power",
        comparator="min",
        lower=450,
        unit="mW",
        verification="fixed structured source",
    )
    baseline = RequirementBaseline(
        project_id=project.id,
        version=1,
        items=(target,),
        change_note="authorized P2 fixed input; not a production plan",
    )
    assignments = []
    for role in SPECIALISTS:
        brief = AgentTaskBrief(
            project_id=project.id,
            baseline_version=1,
            requirement_refs=("R04",),
            specialist=role,
            goal="Read assigned 500 mW source for FIXTURE-" + role,
            specified_params=(SpecifiedParam(name="power", requirement_key="R04", target=target),),
            budget=TaskBudget(model_calls=1, seconds=30),
        )
        evidence = Evidence(
            project_id=project.id,
            source_type="document",
            locator="fixture-" + role,
            excerpt=json.dumps(
                {
                    "subject": "FIXTURE-" + role,
                    "metric": "laser.max_power",
                    "value": {"value": 500, "unit": "mW"},
                    "canary": "CANARY-" + role,
                }
            ),
            page_or_anchor="power",
            source_version="1",
            retrieved_by=RunRef(run_id="p2-fixed-source", actor="user"),
        )
        assignments.append(AssignedTask(brief, (evidence,)).dump())
    return {
        "project": project.model_dump(mode="json"),
        "baseline": baseline.model_dump(mode="json"),
        "assignments": assignments,
    }


def approved_engine():
    from dotenv import dotenv_values
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    settings = dotenv_values(REPO / ".env")
    owner = make_url(settings["MIS_INTEGRATION_OWNER_DATABASE_URL"])
    target = make_url(settings["DEER_FLOW_TEST_DATABASE_URL"])

    def endpoint(u):
        return ((u.host or "").replace("-pooler", ""), u.port or 5432, u.database)

    assert endpoint(owner) == endpoint(target)
    for name in ("MIS_DATABASE_URL", "MIS_TEST_DATABASE_URL"):
        assert endpoint(owner) != endpoint(make_url(settings[name]))
    return create_engine(
        owner.set(drivername="postgresql+psycopg"),
        hide_parameters=True,
        connect_args={"connect_timeout": 15},
    )


def persist():
    from sqlalchemy.orm import Session

    from mis.agents.completion import load_assignments
    from mis.project_service.repository import ProjectService
    from mis.schemas.project import InstrumentProject
    from mis.schemas.requirements import RequirementBaseline

    data = build()
    engine = approved_engine()
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL ROLE mis_app")
            assert connection.exec_driver_sql("SELECT current_user").scalar_one() == "mis_app"
            with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                service = ProjectService(session)
                service.add(InstrumentProject.model_validate(data["project"]))
                service.add(RequirementBaseline.model_validate(data["baseline"]))
                for assigned in load_assignments(data["assignments"]).values():
                    service.add(assigned.brief)
                    for evidence in assigned.evidence:
                        service.add(evidence)
                session.commit()
        return data
    finally:
        engine.dispose()


if __name__ == "__main__":
    print(json.dumps(build()))
