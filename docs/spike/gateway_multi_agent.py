"""One P2-0E bounded real task. No baseline, checkpoint or A4 smoke is repeated.

Workers use the pinned DeerFlow environment; MIS uses its own environment and
approved P2 role. No DDL, automatic model retry, plan adoption or host execution.
"""

import asyncio
import json
import os
import secrets
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path

import httpx
import yaml
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
EVIDENCE = REPO.parent / "mis-p2-gateway-evidence"
BACKEND = REPO.parent / "deer-flow-p2-0a-filtered" / "backend"


def launch():
    class Redacted:
        def __init__(self, stream):
            self.stream = stream

        def write(self, value):
            url = make_url(os.environ["P2_CHECKPOINT_DSN"])
            for secret in (url.password, url.host, os.environ.get("OPENAI_API_KEY")):
                if secret:
                    value = value.replace(secret, "[redacted]")
            return self.stream.write(value)

        def flush(self):
            self.stream.flush()

        def isatty(self):
            return False

    sys.stdout, sys.stderr = Redacted(sys.stdout), Redacted(sys.stderr)
    sys.path.insert(0, str(BACKEND))
    from app.gateway.app import app
    from p2e_budget_guard import P2EGuard as Guard
    from uvicorn import Config, Server

    from mis.agents.responses_model import ModelAsyncClient, close_model_clients

    async def serve():
        server = Server(
            Config(app, host="127.0.0.1", port=18001, workers=1, timeout_graceful_shutdown=15)
        )

        async def stop():
            while not Path(os.environ["P2_E_STOP"]).exists():
                await asyncio.sleep(0.2)
            server.should_exit = True

        watcher = asyncio.create_task(stop())
        cleanup_error = None
        try:
            await server.serve()
        finally:
            watcher.cancel()
            try:
                await close_model_clients()
            except Exception as exc:
                cleanup_error = type(exc).__name__
            payload = {
                "admissions": Guard.admissions,
                "outcomes": Guard.outcomes,
                "reserved_usd": str(Guard.RESERVED_USD),
                "prior_occupancy_usd": str(Guard.PRIOR_OCCUPANCY_USD),
                "client_events": [
                    {"client_id": id(c), "events": c.events, "closed": c.is_closed}
                    for c in ModelAsyncClient.instances
                ],
                "cleanup_error_type": cleanup_error,
            }
            Path(os.environ["P2_E_MODEL_EVIDENCE"]).write_text(
                json.dumps(payload, default=str, indent=2), encoding="utf-8"
            )

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(serve())


def control():
    import p2e_budget_limits as Guard
    from multi_agent_fixture import approved_engine, persist
    from sqlalchemy.orm import Session

    from mis.adapters.artifact_receiver import receive_bundle, request_hash
    from mis.adapters.deerflow import DeerFlowClient, RunBinding, ThreadBinding
    from mis.adapters.task_bridge import brief_hash
    from mis.adapters.task_store import CallBudget, CommandIntent, PostgresTaskRunLinkStore
    from mis.agents.completion import load_assignments
    from mis.agents.profiles import deerflow_profiles
    from mis.project_service.repository import ProjectService

    # Reviewable finite reservation before any real model request.
    assert Guard.MAX_CALLS == 7 and Guard.PRIOR_OCCUPANCY_USD + Guard.RESERVED_USD < Decimal("10")
    outcome_path = EVIDENCE / "agents-live-0e.json"
    with outcome_path.open("x", encoding="utf-8") as handle:
        json.dump(
            {
                "reserved_usd": str(Guard.RESERVED_USD),
                "prior_occupancy_usd": str(Guard.PRIOR_OCCUPANCY_USD),
                "state": "preparing",
            },
            handle,
        )
    settings = dotenv_values(REPO / ".env")
    runtime = make_url(settings["DEER_FLOW_TEST_DATABASE_URL"])
    assert runtime.username == "mis_runtime"
    data = persist()
    assignments = load_assignments(data["assignments"])
    profiles = deerflow_profiles()
    config = yaml.safe_load((EVIDENCE / "gateway.yaml").read_text())
    config.update(profiles["deployment"])
    # Official opt-in management API; model tools remain independently denied.
    config["agents_api"] = {"enabled": True}
    config["models"][0].update(
        use="mis.agents.responses_model:IsolatedResponsesModel",
        api_key="$OPENAI_API_KEY",
        max_tokens=1024,
        max_retries=0,
        timeout=30,
    )
    config["extensions"]["middlewares"] = [
        {"class": "p2e_budget_guard:P2EGuard"},
        {"class": "mis.agents.native_completion:RequiredSpecialistsMiddleware"},
    ]
    config["recursion_limit"] = config["max_recursion_limit"] = 200
    config["llm_call"].update(retry_max_attempts=1, max_concurrent_calls=3)
    # Preserve all denied roles; only the test user Lead gains native task.
    config["authorization"]["provider"]["config"]["roles"]["user"]["tools"] = {"allow": ["task"]}
    config["authorization"]["provider"]["config"]["roles"]["user"]["routes"] = {
        "allow": [
            "threads:read",
            "threads:write",
            "runs:create",
            "runs:read",
            "agents:read",
            "agents:write",
        ]
    }
    for feature in ("title", "suggestions", "summarization", "scheduler"):
        assert config[feature]["enabled"] is False
    assert config["memory"]["enabled"] is False and config["memory"]["injection_enabled"] is False
    assert config["tools"] == [] and config["skills"]
    assert not config["sandbox"].get("allow_host_bash") and not config["sandbox"].get("prewarm")
    path = EVIDENCE / "gateway-0e.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    prefix = "mis-p2-0e-" + secrets.token_hex(6)
    run_id = prefix + "-run"
    stop = EVIDENCE / (prefix + "-stop")
    env = {
        **os.environ,
        "DEER_FLOW_PROJECT_ROOT": str(EVIDENCE),
        "DEER_FLOW_HOME": str(EVIDENCE / "home"),
        "DEER_FLOW_CONFIG_PATH": str(path),
        "P2_ORM_URL": runtime.set(drivername="postgresql", query={}).render_as_string(
            hide_password=False
        ),
        "P2_CHECKPOINT_DSN": runtime.set(drivername="postgresql").render_as_string(
            hide_password=False
        ),
        "PGSSLMODE": "require",
        "OPENAI_API_KEY": settings["LLM_API_KEY"],
        "P2_E_STOP": str(stop),
        "P2_E_MODEL_EVIDENCE": str(outcome_path),
        "LANGSMITH_TRACING": "false",
        "MONOCLE_TRACING": "false",
        "PYTHONIOENCODING": "utf-8",
    }
    log = (EVIDENCE / "gateway-0e.log").open("w", encoding="utf-8")
    process = None
    credential = None
    evidence = {"project_id": data["project"]["id"], "run_id": run_id, "state": "preparing"}
    engine = approved_engine()
    auth = httpx.Client(base_url="http://127.0.0.1:18001", trust_env=False, timeout=60)
    client = httpx.Client(base_url="http://127.0.0.1:18001", trust_env=False, timeout=60)
    try:
        process = subprocess.Popen(
            [str(BACKEND / ".venv/Scripts/python.exe"), str(Path(__file__)), "launch"],
            cwd=BACKEND,
            env=env,
            stdout=log,
            stderr=log,
        )
        for _ in range(80):
            if process.poll() is not None:
                raise RuntimeError("Gateway exited before readiness")
            try:
                if client.get("/health/ready").status_code == 200:
                    break
            except httpx.ConnectError:
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError("Gateway readiness timeout")
        response = auth.post(
            "/api/v1/auth/register",
            json={
                "email": prefix + "@example.com",
                "password": secrets.token_urlsafe(32),
                "remember_me": False,
            },
        )
        response.raise_for_status()
        auth.headers["X-CSRF-Token"] = auth.cookies["csrf_token"]
        issued = auth.post(
            "/api/v1/auth/pats",
            json={
                "name": "P2-0E disposable",
                "expires_in_days": 1,
                "scopes": [
                    "threads:read",
                    "threads:write",
                    "runs:create",
                    "runs:read",
                ],
            },
        )
        issued.raise_for_status()
        credential = issued.json()
        client.headers["Authorization"] = "Bearer " + credential["token"]
        imported = auth.post(
            "/api/agents/import",
            json={
                "format": "deerflow.custom-agent",
                "version": 1,
                "agent": {**profiles["lead_config"], "soul": profiles["lead_soul"]},
            },
        )
        imported.raise_for_status()
        exported = auth.get("/api/agents/project-copilot/export")
        exported.raise_for_status()
        installed = exported.json()["agent"]
        assert installed["memory_enabled"] is False
        assert installed["skills"] == [] and installed["mcp_plugins"] == []
        assert installed["tool_groups"] == []
        assert set(installed["allowed_subagents"]) == {"lab", "research", "procurement"}
        anchor = assignments["lab"].brief
        thread = ThreadBinding(anchor.project_id, anchor.id, prefix, prefix)
        meta = {
            "mis_project_id": anchor.project_id,
            "mis_task_id": anchor.id,
            "mis_thread_id": prefix,
            "mis_run_id": run_id,
        }
        created = client.post(
            "/api/threads",
            json={
                "thread_id": prefix,
                "metadata": {k: v for k, v in meta.items() if k != "mis_run_id"},
            },
        )
        created.raise_for_status()
        body = {
            "assistant_id": "lead_agent",
            "metadata": meta,
            "input": {
                "mis_required_assignments": data["assignments"],
                "messages": [
                    {
                        "type": "human",
                        "content": "Complete assigned MIS roles via native task. "
                        "Use short prompts; MIS supplies each authorized brief. "
                        "After all results return JSON with roles:[lab,research,procurement], "
                        "summaries for every role, "
                        "and status:unreviewed. Do not perform external actions.",
                    }
                ],
            },
            "context": {
                "agent_name": "project-copilot",
                "subagent_enabled": True,
                "thinking_enabled": False,
                "model_name": "gpt-6-luna",
                "max_concurrent_subagents": 3,
                "max_total_subagents": 3,
            },
            "config": {"recursion_limit": 200},
            "multitask_strategy": "reject",
        }
        intent = CommandIntent(
            thread,
            run_id,
            prefix + "-once",
            brief_hash(anchor),
            1,
            "lab",
            __import__("hashlib").sha256(path.read_bytes()).hexdigest(),
            request_hash(body),
            CallBudget(7, 98192, 1024, Guard.RESERVED_USD),
        )
        evidence["request"] = body
        with engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL ROLE mis_app")
            assert PostgresTaskRunLinkStore(connection).begin_intent(intent).created
        with engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL ROLE mis_app")
            PostgresTaskRunLinkStore(connection).mark_uncertain(anchor.project_id, run_id)
        # The only real task POST; no automatic retry even on an uncertain result.
        started = client.post(
            f"/api/threads/{prefix}/runs",
            headers={"Idempotency-Key": intent.idempotency_key},
            json=body,
        )
        started.raise_for_status()
        raw = started.json()
        evidence["native_run"] = raw
        for _ in range(600):
            polled = client.get(f"/api/threads/{prefix}/runs/{raw['run_id']}")
            polled.raise_for_status()
            raw = polled.json()
            evidence["native_run"] = raw
            if raw["status"] not in {"pending", "running"}:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("bounded Run did not terminate")
        for _ in range(30):
            state_response = client.get(f"/api/threads/{prefix}/state")
            state_response.raise_for_status()
            state = state_response.json()
            evidence["thread_state"] = state
            if raw["status"] != "success" or raw["run_id"] in state.get("metadata", {}).get(
                "run_durations", {}
            ):
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("native final state was not persisted in time")
        binding = RunBinding(thread, run_id, raw["run_id"])
        checked = DeerFlowClient._result(binding, raw)
        with engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL ROLE mis_app")
            store = PostgresTaskRunLinkStore(connection)
            command = store.reconcile(anchor.project_id, run_id, checked)
            with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                reception = receive_bundle(
                    ProjectService(session), command, body, state["values"]["messages"]
                )
                session.commit()
        with engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL ROLE mis_app")
            command = PostgresTaskRunLinkStore(connection).get_command(anchor.project_id, run_id)
            with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                replay = receive_bundle(
                    ProjectService(session), command, body, state["values"]["messages"]
                )
                assert reception == replay
                session.commit()
        evidence.update(
            state="finished",
            native_run=raw,
            thread_state=state,
            request=body,
            reception=reception,
            replay_equal=True,
        )
        print(
            json.dumps(
                {
                    "business_status": reception["status"],
                    "roles": reception["roles"],
                    "adoption": reception["adoption"],
                }
            )
        )
    except httpx.HTTPStatusError as exc:
        evidence.update(
            state="failed",
            failure_type=type(exc).__name__,
            http_status=exc.response.status_code,
            route=exc.request.url.path,
        )
        raise
    except Exception as exc:
        evidence.update(state="failed", failure_type=type(exc).__name__)
        raise
    finally:
        if process is not None and process.poll() is None:
            if credential:
                revoked = auth.delete("/api/v1/auth/pats/" + credential["id"])
                evidence["pat_revoke_status"] = revoked.status_code
            auth.post("/api/v1/auth/logout")
            stop.touch()
            process.wait(timeout=60)
            evidence["gateway_exit_code"] = process.returncode
        client.close()
        auth.close()
        engine.dispose()
        log.close()
        (EVIDENCE / "multi-agent-0e.json").write_text(
            json.dumps(evidence, default=str, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "launch":
        launch()
    else:
        control()
