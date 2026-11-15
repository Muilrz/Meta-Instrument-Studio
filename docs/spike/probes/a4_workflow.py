"""Zero-model deterministic workflow via official configured middleware hooks.

Spike-only: use a dedicated Thread with the a4_question_id input channel. Never
enable this fixture in a production agent configuration.
"""

import json

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage
from langgraph.types import interrupt


class A4State(AgentState):
    a4_question_id: str
    a4_completion: dict


class A4Workflow(AgentMiddleware[A4State]):
    state_schema = A4State

    @hook_config(can_jump_to=["end"])
    def before_agent(self, state, runtime):
        question_id = state.get("a4_question_id", "")
        if not question_id.startswith("mis-a4-probe-"):
            raise ValueError("dedicated A4 fixture required")
        response = interrupt({"question_id": question_id, "options": ["fixture-a", "fixture-b"]})
        if (
            not isinstance(response, dict)
            or response.get("question_id") != question_id
            or response.get("answer") not in {"fixture-a", "fixture-b"}
            or not response.get("answer_evidence_id")
            or not response.get("checkpoint_id")
            or not response.get("resume_key")
        ):
            # Remain paused after any unvalidated direct Runtime caller input.
            interrupt({"question_id": question_id, "error": "invalid_response"})
            raise ValueError("A4 invalid response")
        completion = {**response, "completions": 1}
        return {
            "a4_completion": completion,
            "messages": [AIMessage(content=json.dumps(completion), id=question_id + "-result")],
            "jump_to": "end",
        }

    @hook_config(can_jump_to=["end"])
    async def abefore_agent(self, state, runtime):
        return self.before_agent(state, runtime)


class ZeroModelGuard(AgentMiddleware):
    def wrap_model_call(self, request, handler):
        raise RuntimeError("A4 fixture forbids every model invocation")

    async def awrap_model_call(self, request, handler):
        raise RuntimeError("A4 fixture forbids every model invocation")
