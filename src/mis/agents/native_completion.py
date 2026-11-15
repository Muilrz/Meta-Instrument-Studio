"""Official AgentMiddleware binding for the fixed MIS completeness contract.

Import only in pinned DeerFlow, with the manifest supplied by trusted MIS code.
No general scheduler, model invocation, tool execution, retry or business write.
"""

import hashlib
import json

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage

from mis.agents.completion_policy import (
    blocked_response,
    complete_calls,
    complete_summary,
    execution_report,
    load_raw_assignments,
)


class CompletionState(AgentState):
    mis_required_assignments: list[dict]
    mis_completion_repairs: int
    mis_execution_report: dict


class RequiredSpecialistsMiddleware(AgentMiddleware[CompletionState]):
    state_schema = CompletionState

    def before_agent(self, state, runtime):
        # Child graphs deliberately do not inherit the parent's manifest.
        if "mis_required_assignments" not in state:
            return None
        load_raw_assignments(state["mis_required_assignments"])
        return None

    async def abefore_agent(self, state, runtime):
        return self.before_agent(state, runtime)

    @hook_config(can_jump_to=["tools", "end"])
    def after_model(self, state, runtime):
        if "mis_required_assignments" not in state:
            return None
        messages = state["messages"]
        last = messages[-1]
        if not isinstance(last, AIMessage):
            raise ValueError("MIS completion requires an AI response")
        serialized = [m.model_dump(mode="json") for m in messages]
        metadata = last.response_metadata
        blocked = blocked_response(serialized[-1])
        if blocked:
            return {"mis_execution_report": execution_report(serialized, lead_final=False)}
        calls, origins, repaired = complete_calls(
            state["mis_required_assignments"],
            serialized[:-1],
            last.tool_calls,
            repairs=state.get("mis_completion_repairs", 0),
            run_id=runtime.context.get("run_id", "mis-bundle"),
        )
        if calls:
            raw_hash = hashlib.sha256(
                json.dumps(last.model_dump(mode="json"), sort_keys=True, default=str).encode()
            ).hexdigest()
            updated = AIMessage(
                content="",
                id=last.id,
                tool_calls=calls,
                additional_kwargs={
                    **last.additional_kwargs,
                    "mis_call_origins": origins,
                    "mis_original_response_sha256": raw_hash,
                },
                response_metadata=metadata,
                usage_metadata=last.usage_metadata,
            )
            return {
                "messages": [updated],
                "jump_to": "tools",
                "mis_completion_repairs": state.get("mis_completion_repairs", 0) + int(repaired),
            }
        report = execution_report(serialized, lead_final=complete_summary(last.content))
        return {"mis_execution_report": report}

    @hook_config(can_jump_to=["tools", "end"])
    async def aafter_model(self, state, runtime):
        return self.after_model(state, runtime)
