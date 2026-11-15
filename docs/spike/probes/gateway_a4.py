"""Gateway restart/Command.resume fixture. Run with MIS Python; workers use pinned backend.

Uses existing P2 runtime configuration/role; never migrates or sets up a schema.
--persistent uses separately approved tables and mis_app for isolated business
fixtures. Credentials stay in process memory. Model invocations are forbidden.
"""

import asyncio
import hashlib
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
    from mis.adapters.a4_resume import PauseBinding, reconcile_a4_status, resume_request
    from mis.adapters.deerflow import RunBinding, ThreadBinding
    from mis.ids import new_id
    from mis.schemas.base import now
    from mis.schemas.evidence import Evidence
    from mis.schemas.provenance import RunRef
    from mis.schemas.questions import UserQuestion

    persistent = "--persistent" in sys.argv
    suffix = "persistent-0d" if persistent else "0d"
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
    log = (EVIDENCE / f"gateway-a4-{suffix}.log").open("w", encoding="utf-8")
    processes = []
    evidence = {
        "thread_id": prefix,
        "question_id": prefix,
        "model_calls": 0,
        "formal_business_writes": 0,
        "stages": [],
    }
    process = None

    def db_phase(phase, **data):
        child_env = dict(os.environ)
        if credential:
            child_env["P2_A4_PAT"] = credential["token"]
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("a4_persistence.py")), phase],
            input=json.dumps({"prefix": prefix, **data}),
            text=True,
            capture_output=True,
            env=child_env,
            cwd=REPO,
            timeout=180,
        )
        if completed.returncode:
            # Never expose arbitrary stderr/DB exceptions or environment secrets.
            raise RuntimeError(
                "persistent fixture phase failed: " + phase + "; " + completed.stdout[:200]
            )
        result = json.loads(completed.stdout)
        evidence.setdefault("database_phases", []).append(result)
        return result

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

        def settled_state(run_id):
            # Run.success can precede the metadata-only duration checkpoint.
            # Compare replay against the finalized head, not the transient loop
            # checkpoint; this never changes or retries graph execution.
            for _ in range(30):
                snapshot = request("GET", f"/api/threads/{prefix}/state")
                durations = snapshot.get("metadata", {}).get("run_durations", {})
                if isinstance(durations, dict) and run_id in durations:
                    return snapshot
                time.sleep(0.2)
            raise RuntimeError("Run duration checkpoint did not settle")

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
            initial_body = {
                "assistant_id": "lead_agent",
                "metadata": metadata,
                "input": {
                    "a4_question_id": prefix,
                    "messages": [{"type": "human", "content": "A4 fixed fixture"}],
                },
                "context": {"subagent_enabled": False, "thinking_enabled": False},
                "config": {"recursion_limit": 80},
            }
            if persistent:
                prepared = db_phase(
                    "prepare",
                    project_id=project_id,
                    config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
                )
                metadata, initial_body = prepared["metadata"], prepared["body"]
                assert prepared["question_open_before_http"]
                evidence.pop("formal_business_writes", None)
                evidence["business_fixture_record_count_before_http"] = 4
                evidence["formal_experience_writes"] = 0
            request("POST", "/api/threads", json={"thread_id": prefix, "metadata": metadata})
            if persistent:
                assert db_phase("uncertain", run_id=prefix + "-run")["state"] == "uncertain"
            initial = request(
                "POST",
                f"/api/threads/{prefix}/runs",
                headers={"Idempotency-Key": prefix + "-pause"},
                json=initial_body,
            )
            paused_run = await_run(initial["run_id"])
            if persistent:
                assert (
                    db_phase("bind", run_id=prefix + "-run", run=paused_run)["state"] == "completed"
                )
            state = settled_state(initial["run_id"])
            assert state["next"], state
            if persistent:
                assert state["values"]["a4_question_id"] == prefix
                evidence["business_pause_status"] = reconcile_a4_status(
                    paused_run["status"], state, pending_question_id=prefix
                )
                assert evidence["business_pause_status"] == "waiting_user"
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
            (EVIDENCE / f"gateway-a4-{suffix}.json").write_text(
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
                ThreadBinding(project_id, metadata["mis_task_id"], prefix, prefix),
                prefix + "-run",
                initial["run_id"],
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
            if persistent:
                prepared_resume = db_phase("answer_prepare")
                reloaded_resume = db_phase("resume_reload")
                assert prepared_resume["request_sha256"] == reloaded_resume["request_sha256"]
                question = UserQuestion.model_validate(reloaded_resume["question"])
                answer_evidence = Evidence.model_validate(reloaded_resume["evidence"])
                pause = PauseBinding(
                    run,
                    prefix,
                    reloaded_resume["checkpoint_id"],
                    None,
                    reloaded_resume["pending_nodes"][0],
                )
                kwargs.update(
                    current_checkpoint_id=pause.checkpoint_id,
                    current_pending_nodes=tuple(reloaded_resume["pending_nodes"]),
                    observed_interrupt_id=None,
                )
                checkpoint_id = pause.checkpoint_id
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
            if persistent:
                assert body == reloaded_resume["body"]
                assert db_phase("uncertain", run_id=prefix + "-resume-run")["state"] == "uncertain"
            resumed = request(
                "POST", f"/api/threads/{prefix}/runs", headers={"Idempotency-Key": key}, json=body
            )
            completed = await_run(resumed["run_id"])
            final = settled_state(resumed["run_id"])
            evidence.update(resume_body=body, resume_run=completed, final_state=final)
            assert completed["status"] == "success", completed
            assert completed.get("llm_call_count", 0) == 0
            assert not final["next"]
            assert final["values"]["a4_completion"]["answer_evidence_id"] == answer_evidence.id
            assert final["values"]["a4_completion"]["completions"] == 1
            if persistent:
                assert (
                    db_phase("bind", run_id=prefix + "-resume-run", run=completed)["state"]
                    == "completed"
                )
                evidence["business_fixture_record_count"] = 5
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
            if persistent:
                verified = db_phase("verify", resume_body=body)
                assert verified["upstream_run_id"] == resumed["run_id"]
                assert verified["command_reentry_sends_http"] is False
            duplicate = request(
                "POST", f"/api/threads/{prefix}/runs", headers={"Idempotency-Key": key}, json=body
            )
            evidence["duplicate_run_id"] = duplicate["run_id"]
            assert duplicate["run_id"] == resumed["run_id"]
            replay_state = request("GET", f"/api/threads/{prefix}/state")
            evidence["replay_state"] = replay_state
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
                        "question_fixture_persisted_in_mis": persistent,
                        "answer_evidence_persisted_in_mis": persistent,
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
            log_path = EVIDENCE / f"gateway-a4-{suffix}.log"
            text = log_path.read_text(encoding="utf-8", errors="replace")
            for secret in (url.password, url.host, settings.get("LLM_API_KEY"), token):
                if secret:
                    text = text.replace(secret, "[redacted]")
            log_path.write_text(text, encoding="utf-8")
            (EVIDENCE / f"gateway-a4-{suffix}.json").write_text(
                json.dumps(evidence, default=str, indent=2), encoding="utf-8"
            )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "launch":
        launch()
    else:
        control()
