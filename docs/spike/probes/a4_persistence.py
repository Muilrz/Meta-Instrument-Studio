"""Separate MIS client process for the approved P2 persistent A4 fixture.

No DDL or model calls. Input/output contains only fixed fixture records, never
connection strings or PATs. The owner URL is used solely to SET LOCAL ROLE
mis_app on the already approved P2 endpoint. Audit fixtures remain in place.
"""

import hashlib
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import httpx
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def main():
    from mis.adapters.a4_resume import PauseBinding, resume_request
    from mis.adapters.deerflow import DeerFlowClient, RunBinding, ThreadBinding
    from mis.adapters.task_bridge import brief_hash
    from mis.adapters.task_store import CallBudget, CommandIntent, PostgresTaskRunLinkStore
    from mis.project_service.repository import ProjectService
    from mis.schemas.evidence import Evidence
    from mis.schemas.project import InstrumentProject
    from mis.schemas.provenance import RunRef
    from mis.schemas.questions import UserQuestion
    from mis.schemas.requirements import RequirementBaseline, RequirementItem
    from mis.schemas.tasks import AgentTaskBrief

    phase = sys.argv[1]
    supplied = json.load(sys.stdin)
    prefix = supplied["prefix"]
    assert prefix.startswith("mis-a4-probe-")
    settings = dotenv_values(REPO / ".env")
    owner = make_url(settings["MIS_INTEGRATION_OWNER_DATABASE_URL"])
    runtime = make_url(settings["DEER_FLOW_TEST_DATABASE_URL"])

    def endpoint(url):
        return ((url.host or "").replace("-pooler", ""), url.port or 5432, url.database)

    assert endpoint(owner) == endpoint(runtime)
    for name in ("MIS_DATABASE_URL", "MIS_TEST_DATABASE_URL"):
        assert endpoint(owner) != endpoint(make_url(settings[name]))
    engine = create_engine(
        owner.set(drivername="postgresql+psycopg"),
        hide_parameters=True,
        connect_args={"connect_timeout": 15},
    )
    try:
        # HTTP reads precede the business transaction; no DB locks span HTTP.
        state = None
        if phase in {"answer_prepare", "resume_reload"}:
            with httpx.Client(
                base_url="http://127.0.0.1:18001",
                trust_env=False,
                timeout=60,
                headers={"Authorization": "Bearer " + os.environ["P2_A4_PAT"]},
            ) as client:
                response = client.get(f"/api/threads/{prefix}/state")
                response.raise_for_status()
                state = response.json()
            assert state["values"]["a4_question_id"] == prefix
            assert state["next"] == ["A4Workflow.before_agent"]

        with engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL ROLE mis_app")
            assert connection.exec_driver_sql("SELECT current_user").scalar_one() == "mis_app"
            with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                service = ProjectService(session)
                store = PostgresTaskRunLinkStore(connection)
                if phase == "prepare":
                    project = service.add(InstrumentProject(id=supplied["project_id"], name=prefix))
                    service.add(
                        RequirementBaseline(
                            project_id=project.id,
                            version=1,
                            change_note="P2 deterministic fixture",
                            items=(
                                RequirementItem(
                                    key="A4",
                                    name="fixture choice",
                                    metric="preference.fixture",
                                    comparator="enum",
                                    allowed=("fixture-a", "fixture-b"),
                                    verification="user decision",
                                ),
                            ),
                        )
                    )
                    brief = service.add(
                        AgentTaskBrief(
                            project_id=project.id,
                            baseline_version=1,
                            requirement_refs=("A4",),
                            specialist="lab",
                            goal="P2 deterministic zero-model choice",
                        )
                    )
                    context = {
                        "fixture": "p2-persistent-a4",
                        "config_sha256": supplied["config_sha256"],
                        "resume_run_id": prefix + "-resume-run",
                        "resume_key": prefix + "-resume",
                    }
                    question = service.add(
                        UserQuestion(
                            id=prefix,
                            project_id=project.id,
                            run_id=prefix + "-run",
                            brief_id=brief.id,
                            question="Choose fixture",
                            options=("fixture-a", "fixture-b"),
                            context=json.dumps(context, sort_keys=True),
                        )
                    )
                    thread = ThreadBinding(project.id, brief.id, prefix, prefix)
                    metadata = {
                        "mis_project_id": project.id,
                        "mis_task_id": brief.id,
                        "mis_thread_id": prefix,
                        "mis_run_id": question.run_id,
                    }
                    body = {
                        "assistant_id": "lead_agent",
                        "metadata": metadata,
                        "input": {
                            "a4_question_id": prefix,
                            "messages": [{"type": "human", "content": "A4 fixed fixture"}],
                        },
                        "context": {"subagent_enabled": False, "thinking_enabled": False},
                        "config": {"recursion_limit": 80},
                    }
                    intent = CommandIntent(
                        thread,
                        question.run_id,
                        prefix + "-pause",
                        brief_hash(brief),
                        1,
                        "lab",
                        context["config_sha256"],
                        digest(body),
                        CallBudget(0, 0, 0, Decimal(0)),
                    )
                    assert store.begin_intent(intent).created
                    result = {
                        "body": body,
                        "metadata": metadata,
                        "question_id": question.id,
                        "brief_id": brief.id,
                        "question_open_before_http": question.status == "open",
                    }
                else:
                    question = service.get(UserQuestion, prefix)
                    brief = service.get(AgentTaskBrief, question.brief_id)
                    context = json.loads(question.context)
                    if phase == "uncertain":
                        record = store.mark_uncertain(question.project_id, supplied["run_id"])
                        result = {"state": record.state}
                    elif phase == "bind":
                        command = store.get_command(question.project_id, supplied["run_id"])
                        raw = supplied["run"]
                        binding = RunBinding(
                            command.intent.thread, command.intent.run_id, raw["run_id"]
                        )
                        checked = DeerFlowClient._result(binding, raw)
                        record = store.reconcile(
                            question.project_id, command.intent.run_id, checked
                        )
                        result = {"state": record.state, "upstream_run_id": record.upstream_run_id}
                    elif phase in {"answer_prepare", "resume_reload"}:
                        paused = store.get(question.project_id, question.run_id)
                        if phase == "answer_prepare":
                            question = service.answer_question(
                                question.id,
                                answer="fixture-a",
                                run=RunRef(run_id=question.run_id, actor="user"),
                            )
                        evidence = service.get(Evidence, question.answer_evidence_id)
                        pause = PauseBinding(
                            paused.binding,
                            prefix,
                            state["checkpoint_id"],
                            None,
                            "A4Workflow.before_agent",
                        )
                        body = resume_request(
                            pause,
                            question,
                            evidence,
                            answer="fixture-a",
                            resume_key=context["resume_key"],
                            resume_run_id=context["resume_run_id"],
                            current_checkpoint_id=state["checkpoint_id"],
                            observed_interrupt_id=None,
                            current_pending_nodes=tuple(state["next"]),
                        )
                        intent = CommandIntent(
                            paused.binding.thread,
                            context["resume_run_id"],
                            context["resume_key"],
                            brief_hash(brief),
                            1,
                            "lab",
                            context["config_sha256"],
                            digest(body),
                            CallBudget(0, 0, 0, Decimal(0)),
                        )
                        if phase == "answer_prepare":
                            assert store.begin_intent(intent).created
                        else:
                            assert (
                                store.get_command(question.project_id, intent.run_id).intent
                                == intent
                            )
                            assert not store.begin_intent(intent).created
                        result = {
                            "body": body,
                            "request_sha256": digest(body),
                            "question": question.model_dump(mode="json"),
                            "evidence": evidence.model_dump(mode="json"),
                            "checkpoint_id": state["checkpoint_id"],
                            "pending_nodes": state["next"],
                        }
                    elif phase == "verify":
                        evidence = service.get(Evidence, question.answer_evidence_id)
                        resumed = store.get_command(question.project_id, context["resume_run_id"])
                        assert resumed.state == "completed"
                        assert resumed.intent.request_sha256 == digest(supplied["resume_body"])
                        assert not store.begin_intent(resumed.intent).created
                        assert len(service.list(Evidence, question.project_id)) == 1
                        assert len(service.list(UserQuestion, question.project_id)) == 1
                        result = {
                            "question_id": question.id,
                            "answer_evidence_id": evidence.id,
                            "state": resumed.state,
                            "upstream_run_id": resumed.upstream_run_id,
                            "command_reentry_sends_http": False,
                            "evidence_count": 1,
                        }
                    else:
                        raise ValueError("unknown persistent fixture phase")
                session.flush()
                session.commit()
        # The context managers have committed before a parent may send HTTP.
        print(json.dumps({"phase": phase, "pid": os.getpid(), "role": "mis_app", **result}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # DB exceptions may contain hostnames/parameters; never print them.
        print(json.dumps({"failure_type": type(exc).__name__}))
        raise SystemExit(1) from None
