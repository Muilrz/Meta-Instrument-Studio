"""Gateway restart/Command.resume fixture. Run with MIS Python; workers use pinned backend.

Uses existing P2 runtime configuration/role; never migrates or sets up a schema.
Credentials are read in process memory. No model invocation or business writes.
"""

import asyncio
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx
import yaml
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

REPO = Path(__file__).resolve().parents[3]
EVIDENCE = REPO.parent / "mis-p2-gateway-evidence"
BACKEND = REPO.parent / "deer-flow-p2-0a-filtered" / "backend"
sys.path.insert(0, str(REPO / "src"))


def launch():
    class RedactedStream:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def write(self, value):
            connection = make_url(os.environ["P2_CHECKPOINT_DSN"])
            for secret in (
                connection.password,
                connection.host,
                os.environ.get("DEER_FLOW_INTERNAL_AUTH_TOKEN"),
            ):
                if secret:
                    value = value.replace(secret, "[redacted]")
            return self.wrapped.write(value)

        def flush(self):
            self.wrapped.flush()

        def isatty(self):
            return False

    sys.stdout = RedactedStream(sys.stdout)
    sys.stderr = RedactedStream(sys.stderr)
    from uvicorn import Config, Server

    sys.path.insert(0, str(BACKEND))
    from app.gateway.app import app

    async def serve():
        server = Server(
            Config(app, host="127.0.0.1", port=18001, workers=1, timeout_graceful_shutdown=15)
        )

        async def stop():
            while not Path(os.environ["P2_A4_STOP"]).exists():
                await asyncio.sleep(0.2)
            server.should_exit = True

        task = asyncio.create_task(stop())
        try:
            await server.serve()
        finally:
            task.cancel()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(serve())


def control():
    from mis.adapters.a4_resume import PauseBinding, resume_request
    from mis.adapters.deerflow import RunBinding, ThreadBinding
    from mis.ids import new_id
    from mis.schemas.base import now
    from mis.schemas.evidence import Evidence
    from mis.schemas.provenance import RunRef
    from mis.schemas.questions import UserQuestion

    settings = dotenv_values(REPO / ".env")
    url = make_url(settings["DEER_FLOW_TEST_DATABASE_URL"])
    assert url.username == "mis_runtime"
    target = ((url.host or "").replace("-pooler", ""), url.port or 5432, url.database)
    for name in ("MIS_DATABASE_URL", "MIS_TEST_DATABASE_URL"):
        other = make_url(settings[name])
        identity = ((other.host or "").replace("-pooler", ""), other.port or 5432, other.database)
        assert target != identity, "P2 fixture must not use the MIS main/P1 test endpoint"
    config = yaml.safe_load((EVIDENCE / "gateway.yaml").read_text(encoding="utf-8"))
    config["extensions"]["middlewares"] = [
        {"class": "a4_workflow:A4Workflow"},
        {"class": "a4_workflow:ZeroModelGuard"},
    ]
    config["recursion_limit"] = config["max_recursion_limit"] = 80
    # No real credential is available to the model even if the zero-model guard fails.
    config["models"][0]["api_key"] = "a4-model-invocation-forbidden"
    config_path = EVIDENCE / "gateway-a4.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    token = secrets.token_urlsafe(32)
    project_id = new_id("prj")
    prefix = "mis-a4-probe-" + secrets.token_hex(6)
    stop = EVIDENCE / (prefix + "-stop")
    env = dict(os.environ)
    env.update(
        DEER_FLOW_PROJECT_ROOT=str(EVIDENCE),
        DEER_FLOW_HOME=str(EVIDENCE / "home"),
        DEER_FLOW_CONFIG_PATH=str(config_path),
        P2_ORM_URL=url.set(drivername="postgresql", query={}).render_as_string(hide_password=False),
        P2_CHECKPOINT_DSN=url.set(drivername="postgresql").render_as_string(hide_password=False),
        PGSSLMODE="require",
        DEER_FLOW_INTERNAL_AUTH_TOKEN=token,
        P2_A4_STOP=str(stop),
        PYTHONIOENCODING="utf-8",
        LANGSMITH_TRACING="false",
        MONOCLE_TRACING="false",
    )
    python = BACKEND / ".venv" / "Scripts" / "python.exe"
    log = (EVIDENCE / "gateway-a4-0d.log").open("w", encoding="utf-8")
    processes = []
    evidence = {
        "thread_id": prefix,
        "question_id": prefix,
        "model_calls": 0,
        "formal_business_writes": 0,
        "stages": [],
    }
    process = None

    def start():
        if stop.exists():
            stop.unlink()
        instance = subprocess.Popen(
            [str(python), str(Path(__file__)), "launch"],
            cwd=BACKEND,
            env=env,
            stdout=log,
            stderr=log,
        )
        processes.append(instance.pid)
        for _ in range(80):
            if instance.poll() is not None:
                raise RuntimeError("Gateway exited; inspect redacted fixture log")
            try:
                with httpx.Client(trust_env=False) as client:
                    if client.get("http://127.0.0.1:18001/health/ready").status_code == 200:
                        return instance
            except httpx.ConnectError:
                pass
            time.sleep(0.5)
        raise RuntimeError("Gateway startup timed out")

    def shutdown(instance):
        stop.touch()
        instance.wait(timeout=45)
        assert instance.returncode == 0
        evidence.setdefault("gateway_exits", []).append(
            {"launcher_pid": instance.pid, "exit_code": instance.returncode}
        )

    auth = httpx.Client(base_url="http://127.0.0.1:18001", timeout=60, trust_env=False)
    credential = None
    with httpx.Client(base_url="http://127.0.0.1:18001", timeout=60, trust_env=False) as client:

        def request(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        def await_run(run_id):
            for _ in range(160):
                data = request("GET", f"/api/threads/{prefix}/runs/{run_id}")
                if data["status"] not in {"pending", "running"}:
                    time.sleep(0.5)
                    return data
                time.sleep(0.2)
            raise RuntimeError("Run did not terminate")

        try:
            process = start()
            registration = auth.post(
                "/api/v1/auth/register",
                json={
                    "email": prefix + "@example.com",
                    "password": secrets.token_urlsafe(32),
                    "remember_me": False,
                },
            )
            registration.raise_for_status()
            evidence["runtime_user_id"] = registration.json()["id"]
            auth.headers["X-CSRF-Token"] = auth.cookies["csrf_token"]
            issued = auth.post(
                "/api/v1/auth/pats",
                json={
                    "name": "P2 A4 disposable probe",
                    "expires_in_days": 1,
                    "scopes": ["threads:read", "threads:write", "runs:create", "runs:read"],
                },
            )
            issued.raise_for_status()
            credential = issued.json()
            client.headers["Authorization"] = "Bearer " + credential["token"]
            metadata = {
                "mis_project_id": project_id,
                "mis_task_id": "a4",
                "mis_thread_id": prefix,
                "mis_run_id": prefix + "-run",
            }
            request("POST", "/api/threads", json={"thread_id": prefix, "metadata": metadata})
            initial = request(
                "POST",
                f"/api/threads/{prefix}/runs",
                headers={"Idempotency-Key": prefix + "-pause"},
                json={
                    "assistant_id": "lead_agent",
                    "metadata": metadata,
                    "input": {
                        "a4_question_id": prefix,
                        "messages": [{"type": "human", "content": "A4 fixed fixture"}],
                    },
                    "context": {"subagent_enabled": False, "thinking_enabled": False},
                    "config": {"recursion_limit": 80},
                },
            )
            paused_run = await_run(initial["run_id"])
            state = request("GET", f"/api/threads/{prefix}/state")
            assert state["next"], state
            stream = client.get(f"/api/threads/{prefix}/runs/{initial['run_id']}/stream")
            stream.raise_for_status()
            frames = []
            for line in stream.text.splitlines():
                if line.startswith("data: "):
                    try:
                        frames.append(json.loads(line[6:]))
                    except ValueError:
                        pass
            evidence["pause_run"] = paused_run
            evidence["pause_state"] = state
            evidence["pause_stream"] = frames
            (EVIDENCE / "gateway-a4-0d.json").write_text(
                json.dumps(evidence, default=str, indent=2), encoding="utf-8"
            )
            # Native stream exposes pending Interrupt objects as serialized data.
            interrupts = [
                i for f in frames if isinstance(f, dict) for i in f.get("__interrupt__", [])
            ]
            assert len(interrupts) == 1, frames
            interrupt_id = interrupts[0]["id"]
            checkpoint_id = state["checkpoint_id"]
            evidence["interrupt_id"] = interrupt_id
            evidence["stages"].append("paused")
            shutdown(process)
            process = start()
            restored = request("GET", f"/api/threads/{prefix}/state")
            assert restored["checkpoint_id"] == checkpoint_id and restored["next"] == state["next"]
            evidence["restored_state"] = restored
            evidence["stages"].append("restarted_pending")
            run = RunBinding(
                ThreadBinding(project_id, "a4", prefix, prefix), prefix + "-run", initial["run_id"]
            )
            pause = PauseBinding(run, prefix, checkpoint_id, interrupt_id, restored["next"][0])
            question = UserQuestion(
                id=prefix,
                project_id=project_id,
                run_id=run.run_id,
                question="Choose fixture",
                options=("fixture-a", "fixture-b"),
                context="isolated P2 fixture",
            )
            answer_evidence = Evidence(
                project_id=project_id,
                source_type="user_decision",
                locator=question.id,
                excerpt="fixture-a",
                page_or_anchor="answer",
                source_version="1",
                retrieved_by=RunRef(run_id=run.run_id, actor="user"),
            )
            question = UserQuestion.model_validate(
                {
                    **question.model_dump(),
                    "status": "answered",
                    "answer": "fixture-a",
                    "answered_at": now(),
                    "answer_evidence_id": answer_evidence.id,
                }
            )
            key = prefix + "-resume"
            kwargs = dict(
                answer="fixture-a",
                resume_key=key,
                resume_run_id=prefix + "-resume-run",
                current_checkpoint_id=checkpoint_id,
                observed_interrupt_id=interrupt_id,
                current_pending_nodes=tuple(restored["next"]),
            )
            rejected = 0
            for changed in (
                {"answer": "invalid-option"},
                {"current_checkpoint_id": "wrong"},
                {"observed_interrupt_id": "wrong"},
            ):
                try:
                    resume_request(pause, question, answer_evidence, **{**kwargs, **changed})
                except ValueError:
                    rejected += 1
                else:
                    raise AssertionError("mismatched answer was admitted")
            assert rejected == 3
            assert request("GET", f"/api/threads/{prefix}/state")["checkpoint_id"] == checkpoint_id
            body = resume_request(pause, question, answer_evidence, **kwargs)
            resumed = request(
                "POST", f"/api/threads/{prefix}/runs", headers={"Idempotency-Key": key}, json=body
            )
            completed = await_run(resumed["run_id"])
            final = request("GET", f"/api/threads/{prefix}/state")
            evidence.update(resume_body=body, resume_run=completed, final_state=final)
            assert completed["status"] == "success", completed
            assert completed.get("llm_call_count", 0) == 0
            assert not final["next"]
            assert final["values"]["a4_completion"]["answer_evidence_id"] == answer_evidence.id
            assert final["values"]["a4_completion"]["completions"] == 1
            evidence.update(
                resume_body=body,
                resume_run=completed,
                final_state=final,
                rejected_before_post=rejected,
                question_fixture=question.model_dump(mode="json"),
                evidence_fixture=answer_evidence.model_dump(mode="json"),
            )
            evidence["stages"].append("resumed_completed")
            shutdown(process)
            process = start()
            duplicate = request(
                "POST", f"/api/threads/{prefix}/runs", headers={"Idempotency-Key": key}, json=body
            )
            assert duplicate["run_id"] == resumed["run_id"]
            replay_state = request("GET", f"/api/threads/{prefix}/state")
            assert replay_state["values"]["a4_completion"] == final["values"]["a4_completion"]
            assert replay_state["checkpoint_id"] == final["checkpoint_id"]
            changed_body = json.loads(json.dumps(body))
            changed_body["command"]["resume"]["answer"] = "fixture-b"
            conflict = client.post(
                f"/api/threads/{prefix}/runs", headers={"Idempotency-Key": key}, json=changed_body
            )
            assert conflict.status_code == 409, conflict.status_code
            evidence.update(
                duplicate_run_id=duplicate["run_id"],
                replay_state=replay_state,
                changed_answer_same_key_http_status=conflict.status_code,
            )
            evidence["stages"].append("restart_duplicate_and_conflict_checked")
            print(
                json.dumps(
                    {
                        "gateway_a4": "PASS",
                        "stages": evidence["stages"],
                        "question_fixture_persisted_in_mis": False,
                        "answer_evidence_persisted_in_mis": False,
                        "model_calls": 0,
                    }
                )
            )
        finally:
            evidence["process_launcher_pids"] = processes
            if process is not None and process.poll() is None:
                if credential:
                    revoke = auth.delete("/api/v1/auth/pats/" + credential["id"])
                    evidence["pat_revoke_status"] = revoke.status_code
                    auth.post("/api/v1/auth/logout")
                shutdown(process)
            auth.close()
            log.close()
            # Redact all credentials and connection identifiers before leaving logs.
            log_path = EVIDENCE / "gateway-a4-0d.log"
            text = log_path.read_text(encoding="utf-8", errors="replace")
            for secret in (url.password, url.host, settings.get("LLM_API_KEY"), token):
                if secret:
                    text = text.replace(secret, "[redacted]")
            log_path.write_text(text, encoding="utf-8")
            (EVIDENCE / "gateway-a4-0d.json").write_text(
                json.dumps(evidence, default=str, indent=2), encoding="utf-8"
            )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "launch":
        launch()
    else:
        control()
