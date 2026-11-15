import pytest

from mis.agents.completion import AssignedTask
from mis.agents.completion_policy import (
    blocked_response,
    complete_calls,
    complete_summary,
    execution_report,
)
from mis.ids import new_id
from mis.schemas.tasks import TaskBudget


@pytest.fixture
def assignments(records):
    brief, evidence = records[2], records[3]
    return [
        AssignedTask(
            brief.model_copy(
                update={
                    "id": new_id("brf"),
                    "specialist": role,
                    "budget": TaskBudget(model_calls=1),
                }
            ),
            (evidence.model_copy(update={"id": new_id("evd"), "excerpt": "CANARY-" + role}),),
        ).dump()
        for role in ("lab", "research", "procurement")
    ]


def call(role, **kwargs):
    return {
        "name": "task",
        "id": "call-" + role,
        "args": {"subagent_type": role, "prompt": "untrusted other-role data", **kwargs},
    }


def done(role, status="completed"):
    return [
        {"type": "ai", "tool_calls": [call(role)]},
        {
            "type": "tool",
            "tool_call_id": "call-" + role,
            "additional_kwargs": {"subagent_status": status},
        },
    ]


def test_premature_finish_repairs_only_missing_roles_in_one_native_batch(assignments):
    calls, origins, repaired = complete_calls(assignments, done("lab"), [], repairs=0, run_id="r")
    assert repaired and len(calls) == 2
    assert {c["args"]["subagent_type"] for c in calls} == {"research", "procurement"}
    assert set(origins.values()) == {"mis_required_brief"}
    assert complete_calls(assignments, done("lab"), [], repairs=1, run_id="r")[0] == []


def test_normal_batch_stays_native_and_receives_only_its_authorized_brief(assignments):
    calls, origins, repaired = complete_calls(assignments, [], [call("lab")], repairs=0, run_id="r")
    assert not repaired and origins == {"call-lab": "lead"}
    assert "CANARY-lab" in calls[0]["args"]["prompt"]
    assert "CANARY-research" not in calls[0]["args"]["prompt"]
    assert "untrusted other-role data" not in calls[0]["args"]["prompt"]


@pytest.mark.parametrize(
    "proposed",
    [
        [call("lab"), call("lab")],
        [call("other")],
        [call("lab", context_mode="snapshot")],
        [call("lab", model_name="other")],
        [{"name": "bash", "id": "x", "args": {}}],
    ],
)
def test_illegal_dispatch_is_not_repaired_into_permission(assignments, proposed):
    with pytest.raises(ValueError):
        complete_calls(assignments, [], proposed, repairs=0, run_id="r")


def test_failed_role_is_not_automatically_retried(assignments):
    prior = done("lab", "failed")
    calls, _, _ = complete_calls(assignments, prior, [], repairs=0, run_id="r")
    assert all(c["args"]["subagent_type"] != "lab" for c in calls)
    with pytest.raises(ValueError):
        complete_calls(assignments, done("lab"), [call("lab")], repairs=0, run_id="r")


def test_native_receipts_and_lead_summary_both_required():
    messages = done("lab") + done("research") + done("procurement")
    assert execution_report(messages, lead_final=True)["status"] == "completed"
    assert execution_report(messages, lead_final=False)["status"] == "partial"
    assert execution_report(done("lab"), lead_final=True)["status"] == "partial"
    assert execution_report(done("lab", "failed"), lead_final=True)["status"] == "failed"
    assert execution_report([], lead_final=True)["status"] == "missing"


@pytest.mark.parametrize(
    "value",
    ['{"roles":["lab"]}', '{"roles":["lab","lab","lab"]}', "not json", '{"status":"completed"}'],
)
def test_summary_does_not_substitute_for_role_coverage(value):
    assert not complete_summary(value)


def test_assignment_scope_rejects_cross_project(records):
    with pytest.raises(ValueError):
        AssignedTask(records[2], (records[3].model_copy(update={"project_id": new_id("prj")}),))


@pytest.mark.parametrize(
    "message",
    [
        {"additional_kwargs": {"safety_termination": {"detector": "native"}}},
        {"additional_kwargs": {"model_length_termination": {"reason": "length"}}},
        {"additional_kwargs": {"deerflow_error_fallback": True}},
        {"response_metadata": {"status": "incomplete"}},
        {"response_metadata": {"finish_reason": "SAFETY"}},
        {"content": [{"type": "refusal", "refusal": "blocked"}]},
    ],
)
def test_safety_length_and_provider_errors_cannot_trigger_completion_dispatch(message):
    assert blocked_response(message)


def test_final_summary_must_include_three_nonempty_role_summaries():
    assert complete_summary(
        '{"roles":["lab","research","procurement"],"summaries":{"lab":"x","research":"y","procurement":"z"}}'
    )
    assert not complete_summary('{"roles":["lab","research","procurement"]}')
