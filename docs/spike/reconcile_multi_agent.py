"""One-shot read-only Runtime audit and MIS ledger reconciliation after 0E failure.

No Gateway/model call, DDL, Runtime write, retry or Artifact synthesis.
"""

import json
import sys
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))


def main():
    from multi_agent_fixture import approved_engine

    from mis.adapters.deerflow import DeerFlowClient, RunBinding
    from mis.adapters.task_store import PostgresTaskRunLinkStore
    from mis.agents.completion_policy import execution_report
    from mis.project_service.repository import ProjectService
    from mis.schemas.artifacts import AgentArtifact

    folder = REPO.parent / "mis-p2-gateway-evidence"
    attempt = json.loads((folder / "multi-agent-0e.json").read_text())
    model = json.loads((folder / "agents-live-0e.json").read_text())
    assert model["admissions"] == [] and model["outcomes"] == []
    assert all(c["events"] == [] and c["closed"] for c in model["client_events"])
    settings = dotenv_values(REPO / ".env")
    runtime_url = make_url(settings["DEER_FLOW_TEST_DATABASE_URL"])
    assert runtime_url.username == "mis_runtime"
    runtime = create_engine(runtime_url.set(drivername="postgresql+psycopg"), hide_parameters=True)
    business = approved_engine()
    try:
        with runtime.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        "SELECT run_id,thread_id,status,error,metadata_json,llm_call_count,"
                        "total_tokens FROM runs WHERE metadata_json->>'mis_run_id'=:run LIMIT 2"
                    ),
                    {"run": attempt["run_id"]},
                )
                .mappings()
                .all()
            )
        assert len(rows) == 1
        native = dict(rows[0])
        assert (
            native["status"] == "error" and native["llm_call_count"] == native["total_tokens"] == 0
        )
        assert native["error"] == "Sandbox execution is not permitted for your role (role=user)"
        native["metadata"] = native.pop("metadata_json")
        with business.begin() as connection:
            connection.exec_driver_sql("SET LOCAL ROLE mis_app")
            store = PostgresTaskRunLinkStore(connection)
            command = store.get_command(attempt["project_id"], attempt["run_id"])
            binding = RunBinding(command.intent.thread, command.intent.run_id, native["run_id"])
            result = DeerFlowClient._result(binding, native)
            updated = store.reconcile(attempt["project_id"], attempt["run_id"], result)
            assert updated.state == "failed"
            with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                assert ProjectService(session).list(AgentArtifact, attempt["project_id"]) == []
        with business.begin() as connection:
            connection.exec_driver_sql("SET LOCAL ROLE mis_app")
            reloaded = PostgresTaskRunLinkStore(connection).get_command(
                attempt["project_id"], attempt["run_id"]
            )
            assert reloaded == updated
        report = {
            "native_run": native,
            "ledger_state": updated.state,
            "business_status": "failed",
            "execution": execution_report([], lead_final=False),
            "artifact_count": 0,
            "model_calls": 0,
            "actual_usd": "0",
            "ledger_reloaded": True,
            "reconciliation_source": "scoped PostgreSQL SELECT as mis_runtime",
        }
        (folder / "multi-agent-0e-reconciliation.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(json.dumps(report))
    finally:
        runtime.dispose()
        business.dispose()


if __name__ == "__main__":
    main()
