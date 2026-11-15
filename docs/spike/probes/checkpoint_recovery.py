"""Deterministic PostgreSQL checkpoint probe; run with the pinned upstream Python.

Set P2_CHECKPOINT_DSN from the existing test secret in process memory and retain
the same P2_CHECKPOINT_THREAD across separate pause/resume/repeat processes.
This probes LangGraph persistence, not Gateway admission or MIS answer Evidence.
No model, tool, schema setup, or business write occurs.
"""

import asyncio
import json
import os
import sys
from typing import TypedDict

from deerflow.runtime.checkpointer.async_provider import _build_postgres_pool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class State(TypedDict, total=False):
    question_id: str
    answer: str
    completions: int


def approval(state: State) -> State:
    answer = interrupt({"question_id": state["question_id"], "prompt": "choose fixture"})
    if answer != {"question_id": state["question_id"], "choice": "fixture-a"}:
        raise ValueError("answer does not match the durable question")
    return {"answer": answer["choice"], "completions": state.get("completions", 0) + 1}


def build_graph(saver):
    builder = StateGraph(State)
    builder.add_node("approval", approval)
    builder.add_edge(START, "approval")
    builder.add_edge("approval", END)
    return builder.compile(checkpointer=saver)


def validate_answer(snapshot, answer):
    """Spike preflight only; MIS must also bind durable Evidence and principal."""
    if snapshot.next != ("approval",):
        raise ValueError("no matching pending question")
    question = snapshot.tasks[0].interrupts[0].value
    if answer != {"question_id": question["question_id"], "choice": "fixture-a"}:
        raise ValueError("answer does not match the durable question")


def offline_check():
    from langgraph.checkpoint.memory import InMemorySaver

    graph = build_graph(InMemorySaver())
    config = {"configurable": {"thread_id": "offline-question-validation"}}
    graph.invoke({"question_id": "question-0c", "completions": 0}, config)
    before = graph.get_state(config)
    rejected = 0
    for answer in (
        {"question_id": "wrong-question", "choice": "fixture-a"},
        {"question_id": "question-0c", "choice": "unapproved-fixture"},
    ):
        try:
            validate_answer(before, answer)
        except ValueError:
            rejected += 1
    assert rejected == 2
    waiting = graph.get_state(config)
    assert waiting.config == before.config and waiting.next == ("approval",)
    assert waiting.tasks[0].interrupts and waiting.values["completions"] == 0
    valid = {"question_id": "question-0c", "choice": "fixture-a"}
    validate_answer(waiting, valid)
    graph.invoke(Command(resume=valid), config)
    completed = graph.get_state(config)
    graph.invoke(Command(resume=valid), config)
    repeated = graph.get_state(config)
    assert repeated.config == completed.config and repeated.values["completions"] == 1
    print(json.dumps({"offline_rejected_answers": rejected, "pending_preserved": True}))


async def main():
    phase = sys.argv[1]
    assert phase in {"pause", "reject", "resume", "repeat"}
    thread_id = os.environ["P2_CHECKPOINT_THREAD"]
    assert thread_id.startswith("mis-p2-0c-interrupt-")
    config = {"configurable": {"thread_id": thread_id}}
    async with _build_postgres_pool(os.environ["P2_CHECKPOINT_DSN"], "runtime") as pool:
        async with pool.connection() as conn:
            cursor = await conn.execute("SELECT current_user, current_schema()")
            identity = await cursor.fetchone()
            assert identity == {"current_user": "mis_runtime", "current_schema": "runtime"}
        saver = AsyncPostgresSaver(pool)
        graph = build_graph(saver)
        before = await graph.aget_state(config)
        rejected_answers = 0
        if phase == "pause":
            assert not before.values
            result = await graph.ainvoke({"question_id": "question-0c", "completions": 0}, config)
            assert result["__interrupt__"]
        elif phase == "reject":
            assert before.next == ("approval",)
            for answer in (
                {"question_id": "different-question", "choice": "fixture-a"},
                {"question_id": "question-0c", "choice": "unapproved-fixture"},
            ):
                try:
                    validate_answer(before, answer)
                except ValueError:
                    rejected_answers += 1
            assert rejected_answers == 2
        else:
            if phase == "resume":
                assert before.next == ("approval",)
                assert before.tasks[0].interrupts[0].value["question_id"] == "question-0c"
                validate_answer(before, {"question_id": "question-0c", "choice": "fixture-a"})
            else:
                assert before.next == () and before.values["completions"] == 1
            result = await graph.ainvoke(
                Command(resume={"question_id": "question-0c", "choice": "fixture-a"}), config
            )
            assert result["answer"] == "fixture-a" and result["completions"] == 1
        after = await graph.aget_state(config)
        if phase in {"reject", "repeat"}:
            assert after.config == before.config and after.values == before.values
        if phase == "reject":
            assert after.next == ("approval",) and after.tasks[0].interrupts
        if phase == "repeat":
            assert after.values["completions"] == 1
        async with pool.connection() as conn:
            cursor = await conn.execute(
                "SELECT count(*) AS count FROM checkpoints WHERE thread_id=%s", (thread_id,)
            )
            count = (await cursor.fetchone())["count"]
        evidence = {
            "phase": phase,
            "pid": os.getpid(),
            "thread_id": thread_id,
            "identity": identity,
            "saver": type(saver).__name__,
            "before_checkpoint": (before.config or {}).get("configurable", {}).get("checkpoint_id"),
            "after_checkpoint": after.config["configurable"]["checkpoint_id"],
            "values": after.values,
            "next": after.next,
            "interrupts": [i.value for task in after.tasks for i in task.interrupts],
            "checkpoint_rows": count,
            "rejected_answers": rejected_answers,
            "model_calls": 0,
        }
        print(json.dumps(evidence))


if __name__ == "__main__":
    if sys.argv[1] == "offline":
        offline_check()
    else:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
