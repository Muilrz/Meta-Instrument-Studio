"""Run with the pinned upstream backend Python, from its backend directory.

Default: offline, deterministic model; native DeerFlow assembly/task/executor.
--live: explicit budget-reviewed invocation reads the existing LLM_API_KEY.
No database, gateway or sandbox is used in either temporary Harness probe.
"""

import asyncio
import json
import logging
import os
import sys
import tempfile
import threading
import time
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from mis.agents import SPECIALISTS, deerflow_profiles  # noqa: E402


def main():
    logging.disable(logging.CRITICAL)
    live = "--live" in sys.argv
    http_mock = "--http-mock" in sys.argv
    assert not (live and http_mock), "Live and HTTP mock must be separate modes"
    api_key = "offline-not-a-key"
    if live:
        from dotenv import dotenv_values

        api_key = dotenv_values(REPO / ".env")["LLM_API_KEY"]
    with tempfile.TemporaryDirectory(prefix="mis-p2-agents-") as directory:
        home = Path(directory)
        os.environ.update(
            DEER_FLOW_HOME=str(home),
            DEER_FLOW_PROJECT_ROOT=str(home),
            OPENAI_API_KEY=api_key,
        )
        profile = deerflow_profiles()
        config = {
            "config_version": 63,
            "models": [
                {
                    "name": "gpt-6-luna",
                    "use": "langchain_openai:ChatOpenAI",
                    "model": "gpt-6-luna",
                    "api_key": "$OPENAI_API_KEY",
                    "use_responses_api": True,
                    "output_version": "responses/v1",
                    "max_tokens": 1024,
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
            "skills": {"path": str(home / "empty-skills")},
            "tools": [],
            "tool_groups": [],
            "memory": {"enabled": False, "injection_enabled": False},
            "title": {"enabled": False},
            "suggestions": {"enabled": False},
            "summarization": {"enabled": False},
            "scheduler": {"enabled": False},
            "llm_call": {"retry_max_attempts": 1, "max_concurrent_calls": 3},
            "extensions": {"middlewares": [{"class": "p2_agent_budget_guard:P2AgentBudgetGuard"}]},
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
            **profile["deployment"],
        }
        if http_mock:
            config["models"][0]["use"] = "p2_http_model:OfflineResponsesModel"
        import yaml

        config_path = home / "config.yaml"
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
        os.environ["DEER_FLOW_CONFIG_PATH"] = str(config_path)

        from deerflow.config import get_app_config
        from deerflow.persistence.agents import get_agent_store
        from langchain_core.language_models.chat_models import BaseChatModel
        from langchain_core.messages import AIMessage, ToolMessage
        from langchain_core.outputs import ChatGeneration, ChatResult

        app_config = get_app_config()
        get_agent_store().create(
            "project-copilot", profile["lead_config"], profile["lead_soul"], user_id="default"
        )

        observations = []
        intervals = {}
        lock = threading.Lock()
        barrier = threading.Barrier(3, timeout=15)

        class MockModel(BaseChatModel):
            model_name: str = "gpt-6-luna"
            use_responses_api: bool = True
            max_retries: int = 0
            max_tokens: int = 1024
            root_client: Any = SimpleNamespace(base_url="https://api.openai.com/v1/")

            @property
            def _llm_type(self):
                return "mis-fixed-offline"

            def bind_tools(self, tools, **kwargs):
                return self

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                text = "\n".join(str(m.content) for m in messages)
                role = next(
                    (r for r in SPECIALISTS if f"You are MIS {r} Specialist." in text), None
                )
                if role:
                    with lock:
                        observations.append({"role": role, "input": text})
                        intervals[role] = [time.perf_counter(), None]
                    barrier.wait()
                    time.sleep(0.02)
                    with lock:
                        intervals[role][1] = time.perf_counter()
                    answer = {
                        "role": role,
                        "task_id": f"task-{role}",
                        "summary": f"{role} fixed candidate",
                        "evidence_refs": [f"EV-{role}"],
                        "unknowns": ["unverified"],
                    }
                    message = AIMessage(
                        content=[
                            {
                                "type": "text",
                                "text": json.dumps(answer),
                                "annotations": [],
                                "phase": "final_answer",
                            }
                        ]
                    )
                elif any(isinstance(m, ToolMessage) for m in messages):
                    results = [str(m.content) for m in messages if isinstance(m, ToolMessage)]
                    assert all(f"{r} fixed candidate" in "\n".join(results) for r in SPECIALISTS)
                    message = AIMessage(
                        content=json.dumps({"summaries": list(SPECIALISTS), "status": "unreviewed"})
                    )
                else:
                    message = AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "task",
                                "id": f"dispatch-{r}",
                                "type": "tool_call",
                                "args": {
                                    "subagent_type": r,
                                    "context_mode": "isolated",
                                    "prompt": json.dumps(
                                        {
                                            "project_id": "project-A",
                                            "task_id": f"task-{r}",
                                            "role": r,
                                            "canary": f"CANARY-{r}",
                                            "evidence_refs": [f"EV-{r}"],
                                        }
                                    ),
                                },
                            }
                            for r in SPECIALISTS
                        ],
                    )
                return ChatResult(generations=[ChatGeneration(message=message)])

        from deerflow.agents.lead_agent import agent as lead_module
        from deerflow.agents.lead_agent.agent import assemble_lead_agent
        from deerflow.agents.middlewares import tool_error_handling_middleware as child_module
        from deerflow.runtime.assembly_evidence import capture_assembly

        lead_builder = lead_module.build_middlewares
        child_builder = child_module.build_subagent_runtime_middlewares
        middleware_checks = []

        def check_lead(*args, **kwargs):
            middlewares = lead_builder(*args, **kwargs)
            names = [type(m).__name__ for m in middlewares]
            assert "MemoryMiddleware" not in names
            dynamic = next(m for m in middlewares if type(m).__name__ == "DynamicContextMiddleware")
            assert dynamic._memory_enabled is False
            middleware_checks.append("lead-no-memory")
            return middlewares

        def check_child(*args, **kwargs):
            middlewares = child_builder(*args, **kwargs)
            names = [type(m).__name__ for m in middlewares]
            assert "MemoryMiddleware" not in names
            assert "DynamicContextMiddleware" not in names
            assert "SubagentDateContextMiddleware" in names
            middleware_checks.append("child-date-only")
            return middlewares

        def no_sandbox(*args, **kwargs):
            raise AssertionError("Sandbox acquisition is forbidden in this offline test")

        async def no_sandbox_async(*args, **kwargs):
            no_sandbox()

        run_config = {
            "configurable": {"thread_id": "mis-agent-offline"},
            "context": {
                "user_id": "default",
                "user_role": "user",
                "agent_name": "project-copilot",
                "model_name": "gpt-6-luna",
                "subagent_enabled": True,
                "thinking_enabled": False,
                "max_concurrent_subagents": 3,
                "max_total_subagents": 3,
            },
            "recursion_limit": 100,
        }
        from deerflow.tools.builtins.task_tool import task_tool
        from p2_agent_budget_guard import P2AgentBudgetGuard

        async def rejected_roles():
            runtime = SimpleNamespace(
                context={"app_config": app_config},
                config={"metadata": {"allowed_subagents": []}},
                state={"messages": []},
            )
            for role in ("lab", "bash", "nonexistent-role"):
                rejected = await task_tool.coroutine(
                    runtime=runtime,
                    prompt="Denied task",
                    subagent_type=role,
                    tool_call_id="deny-" + role,
                )
                assert (
                    rejected.update["messages"][0].additional_kwargs["subagent_status"] == "failed"
                )

        asyncio.run(rejected_roles())

        P2AgentBudgetGuard.admissions.clear()
        P2AgentBudgetGuard.outcomes.clear()
        from verify_agent_guard import verify

        verify()
        with ExitStack() as stack:
            stack.enter_context(capture_assembly())
            stack.enter_context(patch.object(lead_module, "build_middlewares", check_lead))
            stack.enter_context(
                patch.object(child_module, "build_subagent_runtime_middlewares", check_child)
            )
            if not live and not http_mock:
                stack.enter_context(
                    patch(
                        "deerflow.agents.lead_agent.agent.create_chat_model",
                        return_value=MockModel(),
                    )
                )
                stack.enter_context(
                    patch("deerflow.subagents.executor.create_chat_model", return_value=MockModel())
                )
            stack.enter_context(
                patch("deerflow.sandbox.middleware.SandboxMiddleware._acquire_sandbox", no_sandbox)
            )
            stack.enter_context(
                patch(
                    "deerflow.sandbox.middleware.SandboxMiddleware._acquire_sandbox_async",
                    no_sandbox_async,
                )
            )
            if live:
                from deerflow.models import create_chat_model

                model = create_chat_model("gpt-6-luna", app_config=app_config, attach_tracing=False)
                assert str(model.root_client.base_url) == "https://api.openai.com/v1/"
                assert app_config.llm_call.retry_max_attempts == 1
            assembly = assemble_lead_agent(run_config, app_config=app_config)
            assert [t.name for t in assembly.descriptor.tools] == ["task"]
            prompt = (
                "Execute exactly these three independent MIS TaskBriefs. First call task THREE "
                "times in ONE parallel tool-call batch: lab, research, procurement. "
                "Use context_mode=isolated. Give each child ONLY its own JSON brief below. "
                "Each child returns JSON role/task_id/summary/evidence_refs/unknowns, "
                "using only supplied material. Do not use other tools or ask questions. "
                "After all three results return, give a short JSON aggregation with roles, "
                "evidence_refs, unknowns, status=unreviewed. Do not delegate again.\n"
                + "\n".join(
                    json.dumps(
                        {
                            "project_id": "project-A",
                            "task_id": f"task-{r}",
                            "role": r,
                            "canary": f"CANARY-{r}",
                            "evidence_refs": [f"EV-{r}"],
                            "data": "Fixed mock input: spectral resolution requirement 4 cm^-1; "
                            "available resolution unknown. No other facts are supplied.",
                        }
                    )
                    for r in SPECIALISTS
                )
            )
            try:
                result = asyncio.run(
                    assembly.graph.ainvoke(
                        {"messages": [{"type": "human", "content": prompt}]},
                        run_config,
                        context=run_config["context"],
                    )
                )
            finally:
                if live:
                    evidence = REPO.parent / "mis-p2-gateway-evidence" / "agents-live.json"
                    evidence.write_text(
                        json.dumps(
                            {
                                "reserved_usd": str(P2AgentBudgetGuard.RESERVED_USD),
                                "admissions": P2AgentBudgetGuard.admissions,
                                "outcomes": P2AgentBudgetGuard.outcomes,
                                "final_messages": [
                                    m.model_dump(mode="json") for m in result["messages"]
                                ]
                                if "result" in locals()
                                else None,
                            },
                            default=str,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
        assert 0 < len(P2AgentBudgetGuard.admissions) <= P2AgentBudgetGuard.MAX_CALLS
        if not live:
            assert len(P2AgentBudgetGuard.admissions) == 5
        assert sum(not a["tools"] for a in P2AgentBudgetGuard.admissions) == 3
        assert middleware_checks.count("lead-no-memory") == 1
        assert middleware_checks.count("child-date-only") == 3
        if http_mock:
            children = [a for a in P2AgentBudgetGuard.admissions if not a["tools"]]
            assert max(a["started"] for a in children) < min(a["finished"] for a in children), [
                {key: a.get(key) for key in ("started", "finished", "error_types")}
                for a in children
            ]
            for child in children:
                text = json.dumps(child["messages"])
                assert sum(f"CANARY-{role}" in text for role in SPECIALISTS) == 1
                assert not child.get("error_types")
            assert "unreviewed" in str(result["messages"][-1].content)
            print("HTTP_NATIVE_CHAIN_PASS; real_ChatOpenAI_SDK=5; external_requests=0")
            print(
                json.dumps(
                    {
                        "child_intervals": [
                            {key: child.get(key) for key in ("started", "finished", "error_types")}
                            for child in children
                        ],
                        "clock_resolution": time.get_clock_info("perf_counter").resolution,
                    }
                )
            )
            return
        if live:
            final = result["messages"][-1]
            assert not final.additional_kwargs.get("deerflow_error_fallback"), "Live Lead failed"
            assert "unreviewed" in str(final.content), "Live aggregation was not returned"
            calls = {
                call["id"]: call["args"]["subagent_type"]
                for message in result["messages"]
                for call in getattr(message, "tool_calls", [])
            }
            completed = {
                calls[message.tool_call_id]
                for message in result["messages"]
                if isinstance(message, ToolMessage)
                and message.tool_call_id in calls
                and message.additional_kwargs.get("subagent_status") == "completed"
            }
            assert completed == set(SPECIALISTS), "Not all live specialists completed"
            print(
                json.dumps(
                    {
                        "real_model_calls": len(P2AgentBudgetGuard.admissions),
                        "reserved_usd": str(P2AgentBudgetGuard.RESERVED_USD),
                        "final": result["messages"][-1].content,
                    }
                )
            )
            return
        assert len(observations) == 3, observations
        for observation in observations:
            role = observation["role"]
            assert f"CANARY-{role}" in observation["input"]
            for other in SPECIALISTS:
                if other != role:
                    assert f"CANARY-{other}" not in observation["input"]
        assert max(i[0] for i in intervals.values()) < min(i[1] for i in intervals.values())
        assert "unreviewed" in result["messages"][-1].content
        assert not result.get("sandbox")
        print(
            json.dumps(
                {
                    "native_lead_task_executor": "PASS",
                    "parallel_specialists": 3,
                    "isolated_canaries": "PASS",
                    "sandbox_acquisitions": 0,
                    "real_model_calls": 0,
                    "final": result["messages"][-1].content,
                }
            )
        )


if __name__ == "__main__":
    main()
