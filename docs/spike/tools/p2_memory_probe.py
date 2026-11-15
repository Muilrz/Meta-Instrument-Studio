"""Deterministic probes against the pinned DeerFlow environment; no Gateway or LLM.

Run with DeerFlow backend/.venv/Scripts/python.exe from its backend directory.
Only an automatically removed temporary directory receives canary data.
"""

import asyncio
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


def main():
    results = {}
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
    ).strip()
    assert commit == "58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a", "wrong upstream checkout"
    results["upstream_commit"] = commit
    connect = socket.socket.connect

    def loopback_only(sock, address):
        # Windows asyncio implements socketpair with a loopback connection.
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return connect(sock, address)
        raise AssertionError("external network forbidden")

    class Request:
        def __init__(self, messages, runtime):
            self.messages = messages
            self.runtime = runtime

        def override(self, **kwargs):
            return Request(kwargs.get("messages", self.messages), self.runtime)

    def capture_request(request):
        assert "PROJECT_A_CANARY_9971" not in str(request.messages)
        assert not any("<memory>" in str(message.content) for message in request.messages)
        return "fake-handler-only"

    async def capture_async_request(request):
        return capture_request(request)

    def content_snapshot(root):
        return {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*")
            if path.is_file() and path.suffix in (".md", ".json")
        }

    with tempfile.TemporaryDirectory(prefix="mis-p2-memory-") as directory:
        root = Path(directory)
        os.environ["DEER_FLOW_HOME"] = str(root / "home")
        # Never permit a probe to fall through to an external service.
        with (
            patch.object(socket.socket, "connect", loopback_only),
            patch("dotenv.load_dotenv", return_value=False),
        ):
            from deerflow.agents.lead_agent.prompt import _get_memory_context
            from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
            from deerflow.agents.memory.summarization_hook import memory_flush_hook
            from deerflow.agents.middlewares.dynamic_context_middleware import (
                DynamicContextMiddleware,
                _format_current_date,
            )
            from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
            from deerflow.config.app_config import AppConfig
            from deerflow.config.memory_config import MemoryConfig
            from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
            from langgraph.graph.message import add_messages
            from langgraph.runtime import Runtime

            disabled = MemoryConfig(enabled=False, injection_enabled=False)
            config = AppConfig(
                memory=disabled,
                sandbox={"use": "deerflow.community.aio_sandbox:AioSandboxProvider"},
            )
            get_manager = Mock(side_effect=AssertionError("disabled path accessed manager"))
            state = {
                "messages": [
                    HumanMessage(content="PROJECT_A_CANARY_9971", id="a-user"),
                    AIMessage(content="PROJECT_A_RESULT_9971", id="a-ai"),
                ]
            }
            runtime = Runtime(context={"thread_id": "a", "user_id": "shared-user"})
            with patch(
                "deerflow.agents.middlewares.memory_middleware.get_memory_manager", get_manager
            ):
                middleware = MemoryMiddleware(memory_config=disabled)
                assert middleware.after_agent(state, runtime) is None
                assert asyncio.run(middleware.aafter_agent(state, runtime)) is None
            get_manager.assert_not_called()
            results["disabled_sync_async_write"] = "PASS: manager never acquired"

            with (
                patch(
                    "deerflow.agents.memory.summarization_hook.get_memory_config",
                    return_value=disabled,
                ),
                patch("deerflow.agents.memory.summarization_hook.get_memory_manager", get_manager),
            ):
                memory_flush_hook(
                    SimpleNamespace(thread_id="a", messages_to_summarize=state["messages"])
                )
            get_manager.assert_not_called()
            results["disabled_compaction_flush"] = "PASS: manager never acquired"

            with patch("deerflow.agents.memory.get_memory_manager", get_manager):
                assert _get_memory_context(app_config=config, user_id="shared-user") == ""
            get_manager.assert_not_called()
            results["disabled_memory_read"] = "PASS: manager never acquired"

            # Put a real canary into an isolated native file store. Import is a
            # deterministic fixture operation, never an extraction/model call.
            llm = Mock()
            llm.invoke.side_effect = AssertionError("model forbidden")
            llm.ainvoke.side_effect = AssertionError("model forbidden")
            manager = DeerMem(
                backend_config={
                    "storage_path": str(root / "memory"),
                    "host_llm": llm,
                    "token_counting": "char",
                    "retrieval_relevance_enabled": False,
                }
            )
            try:
                index = root / "memory" / ".retrieval" / "memory-fts5.sqlite3"
                assert index.is_file()
                with closing(
                    sqlite3.connect(f"file:{index.as_posix()}?mode=ro", uri=True)
                ) as connection:
                    count = connection.execute("SELECT count(*) FROM memory_fts").fetchone()[0]
                assert count == 0
                assert manager.warm() is True
                results["empty_fts_initialization"] = (
                    "REPRODUCED: constructor creates empty index; warm has no model call"
                )
                manager.import_memory(
                    {
                        "version": "1.0",
                        "user": {},
                        "history": {},
                        "facts": [
                            {
                                "id": "fact_project_a_canary",
                                "content": "PROJECT_A_CANARY_9971",
                                "category": "context",
                                "confidence": 1.0,
                                "source": "isolated-fixture",
                            }
                        ],
                    },
                    user_id="shared-user",
                )
                assert "PROJECT_A_CANARY_9971" in json.dumps(
                    manager.get_memory(user_id="shared-user")
                )
                enabled_config = config.model_copy(
                    update={"memory": MemoryConfig(enabled=True, injection_enabled=True)}
                )
                with patch("deerflow.agents.memory.get_memory_manager", return_value=manager):
                    recalled = _get_memory_context(app_config=enabled_config, user_id="shared-user")
                assert "PROJECT_A_CANARY_9971" in recalled
                results["enabled_negative_control"] = (
                    "CONFIRMED: same-user native memory contains canary; no project scope"
                )
                snapshot = content_snapshot(root)
                assert snapshot
                with (
                    patch(
                        "deerflow.agents.memory.get_memory_manager", return_value=manager
                    ) as acquire,
                    patch.object(
                        type(manager), "get_context", side_effect=AssertionError("read forbidden")
                    ),
                ):
                    for project in ("project-b", "project-c"):
                        mw = DynamicContextMiddleware(app_config=config, memory_enabled=False)
                        b_runtime = Runtime(
                            context={
                                "user_id": "shared-user",
                                "thread_id": project,
                                "project_id": project,
                            }
                        )
                        b_state = {
                            "messages": [
                                HumanMessage(content="Only use this project's brief", id=project)
                            ]
                        }
                        update = mw.before_agent(b_state, b_runtime)
                        messages = add_messages(b_state["messages"], update["messages"])
                        assert "PROJECT_A_CANARY_9971" not in str(messages)
                        assert not any("<memory>" in str(message.content) for message in messages)
                        assert (
                            mw.wrap_model_call(Request(messages, b_runtime), capture_request)
                            == "fake-handler-only"
                        )
                        async_update = asyncio.run(mw.abefore_agent(b_state, b_runtime))
                        assert "PROJECT_A_CANARY_9971" not in str(async_update)
                        assert (
                            asyncio.run(
                                mw.awrap_model_call(
                                    Request(
                                        add_messages(b_state["messages"], async_update["messages"]),
                                        b_runtime,
                                    ),
                                    capture_async_request,
                                )
                            )
                            == "fake-handler-only"
                        )
                    acquire.assert_not_called()
                assert snapshot == content_snapshot(root)
                llm.invoke.assert_not_called()
                llm.ainvoke.assert_not_called()
                results["same_user_cross_project_canary"] = (
                    "PASS: 2 fresh projects, sync/async, no manager read or canary injection"
                )

                date = _format_current_date()
                frozen = HumanMessage(
                    content="<memory>PROJECT_A_CANARY_9971</memory>",
                    id="old__memory",
                    additional_kwargs={"dynamic_context_reminder": True, "hide_from_ui": True},
                )
                prior = [
                    SystemMessage(
                        content=f"<current_date>{date}</current_date>",
                        id="old",
                        additional_kwargs={"dynamic_context_reminder": True, "reminder_date": date},
                    ),
                    frozen,
                    HumanMessage(content="new project", id="new"),
                ]
                unsafe_mw = DynamicContextMiddleware(app_config=config)
                update = unsafe_mw.before_agent({"messages": prior}, runtime)
                retained = add_messages(prior, (update or {}).get("messages", []))
                assert "PROJECT_A_CANARY_9971" in str(retained)
                results["config_flags_only_frozen_memory"] = (
                    "GAP REPRODUCED: flags alone retain historical frozen memory"
                )
                safe_mw = DynamicContextMiddleware(app_config=config, memory_enabled=False)
                update = safe_mw.before_agent({"messages": prior}, runtime)
                cleaned = add_messages(prior, update["messages"])
                assert "PROJECT_A_CANARY_9971" not in str(cleaned)
                update = asyncio.run(safe_mw.abefore_agent({"messages": prior}, runtime))
                assert "PROJECT_A_CANARY_9971" not in str(add_messages(prior, update["messages"]))
                results["profile_opt_out_frozen_memory"] = (
                    "PASS: memory_enabled=False removes owned frozen memory sync/async"
                )
                results["model_calls"] = 0
                results["formal_memory_writes"] = 0
            finally:
                manager.close()
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
