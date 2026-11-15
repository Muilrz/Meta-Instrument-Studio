"""Offline native graph + official SDK proof of bounded completion; no live mode."""

import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))


def main():
    from p2e_budget_guard import P2EGuard as Guard
    from p2e_http_model import OBSERVATIONS

    from mis.agents.profiles import SPECIALISTS, deerflow_profiles
    from mis.agents.responses_model import close_model_clients

    logging.disable(logging.CRITICAL)
    with tempfile.TemporaryDirectory(prefix="mis-p2-0e-") as directory:
        home = Path(directory)
        os.environ.update(
            DEER_FLOW_HOME=str(home),
            DEER_FLOW_PROJECT_ROOT=str(home),
            OPENAI_API_KEY="offline-not-a-key",
        )
        profiles = deerflow_profiles()
        config = {
            "config_version": 63,
            "models": [
                {
                    "name": "gpt-6-luna",
                    "use": "p2e_http_model:OfflineCompletionModel",
                    "model": "gpt-6-luna",
                    "api_key": "offline-not-a-key",
                    "max_tokens": 1024,
                    "use_responses_api": True,
                    "output_version": "responses/v1",
                    "max_retries": 0,
                    "timeout": 30,
                    "reasoning_effort": "none",
                    "supports_reasoning_effort": True,
                    "when_thinking_disabled": {"reasoning_effort": "none"},
                }
            ],
            "database": {"backend": "memory"},
            "checkpointer": {"type": "memory"},
            "sandbox": {
                "use": "deerflow.community.aio_sandbox:AioSandboxProvider",
                "allow_host_bash": False,
                "prewarm": False,
            },
            "tools": [],
            "tool_groups": [],
            "skills": {"path": str(home / "empty-skills")},
            "memory": {"enabled": False, "injection_enabled": False},
            "title": {"enabled": False},
            "suggestions": {"enabled": False},
            "summarization": {"enabled": False},
            "scheduler": {"enabled": False},
            "llm_call": {"retry_max_attempts": 1, "max_concurrent_calls": 3},
            "extensions": {
                "middlewares": [
                    {"class": "p2e_budget_guard:P2EGuard"},
                    {"class": "mis.agents.native_completion:RequiredSpecialistsMiddleware"},
                ]
            },
            "authorization": {
                "enabled": True,
                "fail_closed": True,
                "default_role": "user",
                "provider": {
                    "use": "deerflow.authz.rbac:RbacAuthorizationProvider",
                    "config": {
                        "roles": {
                            "user": {
                                "tools": {"allow": ["task"]},
                                "sandbox": {"allow": False},
                                "skills": {"allow": False},
                                "models": {"allow": ["gpt-6-luna"]},
                            }
                        }
                    },
                },
            },
            **profiles["deployment"],
        }
        path = home / "config.yaml"
        path.write_text(yaml.safe_dump(config), encoding="utf-8")
        os.environ["DEER_FLOW_CONFIG_PATH"] = str(path)
        from deerflow.agents.lead_agent.agent import assemble_lead_agent
        from deerflow.config import get_app_config
        from deerflow.persistence.agents import get_agent_store
        from deerflow.runtime.assembly_evidence import capture_assembly

        app = get_app_config()
        get_agent_store().create(
            "project-copilot", profiles["lead_config"], profiles["lead_soul"], user_id="default"
        )
        prepared = subprocess.run(
            [
                str(REPO / ".venv" / "Scripts" / "python.exe"),
                str(Path(__file__).with_name("multi_agent_fixture.py")),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assignments = json.loads(prepared.stdout)["assignments"]
        context = {
            "user_id": "default",
            "user_role": "user",
            "agent_name": "project-copilot",
            "model_name": "gpt-6-luna",
            "subagent_enabled": True,
            "thinking_enabled": False,
            "max_concurrent_subagents": 3,
            "max_total_subagents": 3,
            "run_id": "offline-0e",
        }
        projection_denied = os.environ.get("P2E_PROJECTION_DENIED") == "1"
        if projection_denied:
            context["thread_id"] = "offline-0e"
        run_config = {
            "configurable": {"thread_id": "offline-0e"},
            "context": context,
            "recursion_limit": 200,
        }
        Guard.admissions.clear()
        Guard.outcomes.clear()

        def forbidden(*args, **kwargs):
            raise AssertionError("Sandbox acquisition forbidden")

        async def run():
            try:
                assembly = assemble_lead_agent(run_config, app_config=app)
                assert [t.name for t in assembly.descriptor.tools] == ["task"]
                return await assembly.graph.ainvoke(
                    {
                        "messages": [
                            {
                                "type": "human",
                                "content": "Run the required MIS roles and summarize JSON roles.",
                            }
                        ],
                        "mis_required_assignments": assignments,
                    },
                    run_config,
                    context=context,
                )
            finally:
                await close_model_clients()

        with (
            capture_assembly(),
            patch("deerflow.sandbox.middleware.SandboxMiddleware._acquire_sandbox", forbidden),
            patch(
                "deerflow.sandbox.middleware.SandboxMiddleware._acquire_sandbox_async", forbidden
            ),
            (
                patch(
                    "deerflow.sandbox.middleware.SandboxMiddleware._prepare_agent_skill_projection",
                    return_value="offline-policy-projection",
                )
                if projection_denied
                else nullcontext()
            ),
        ):
            try:
                result = asyncio.run(run())
            except Exception as exc:
                if not projection_denied or type(exc).__name__ != "SandboxAuthorizationError":
                    raise
                assert Guard.admissions == [] and OBSERVATIONS == []
                print(json.dumps({"projection_denial": "PASS", "sdk_requests": 0}))
                return
        assert not projection_denied, "policy-scoped context must fail closed"
        failed = os.environ.get("P2E_OFFLINE_FAILURE") == "research"
        assert result["mis_execution_report"]["status"] == ("partial" if failed else "completed"), (
            result.get("mis_execution_report")
        )
        if failed:
            assert result["mis_execution_report"]["roles"]["research"] == "failed"
        assert result["mis_completion_repairs"] == 1
        assert len(Guard.admissions) == 6
        assert len(OBSERVATIONS) == 3
        receipts = [m for m in result["messages"] if m.type == "tool"]
        assert len(receipts) == 3
        for message in receipts:
            receipt = message.additional_kwargs["deerflow_tool_receipt"]
            assert receipt["tool_name"] == "task"
            assert receipt["tool_call_id"] == message.tool_call_id
            if message.additional_kwargs["subagent_status"] == "completed":
                assert receipt["status"] == "success"
                assert json.loads(message.additional_kwargs["subagent_result_brief"])["claims"]
            else:
                assert receipt["status"] != "success"
        for role, text in OBSERVATIONS:
            assert "CANARY-" + role in text
            assert all("CANARY-" + other not in text for other in SPECIALISTS if other != role)
        children = [a for a in Guard.admissions if not a["tools"]]
        assert len(children) == 3
        assert max(a["started"] for a in children[1:]) < min(a["finished"] for a in children[1:])
        print(
            json.dumps(
                {
                    "native_completion": "PASS",
                    "fault_injected": failed,
                    "sdk_requests": 6,
                    "repair_batches": 1,
                    "parallel_repaired_roles": 2,
                    "report": result["mis_execution_report"],
                    "external_requests": 0,
                }
            )
        )


if __name__ == "__main__":
    main()
