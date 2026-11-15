import pytest

from mis.agents.results import require_complete_specialists, specialist_statuses


def messages(roles=("lab", "research", "procurement"), status="completed"):
    return [
        {
            "type": "ai",
            "tool_calls": [
                {"name": "task", "id": role, "args": {"subagent_type": role}} for role in roles
            ],
        },
        *[
            {"type": "tool", "tool_call_id": role, "additional_kwargs": {"subagent_status": status}}
            for role in roles
        ],
        {
            "type": "ai",
            "content": '{"status":"unreviewed","roles":["lab","research","procurement"]}',
        },
    ]


def test_all_receipts_complete_and_summary_is_not_business_acceptance():
    assert set(require_complete_specialists(messages()).values()) == {"completed"}


def test_lead_summary_does_not_invent_missing_specialists():
    sample = messages(("lab",))
    assert specialist_statuses(sample) == {
        "lab": "completed",
        "research": "missing",
        "procurement": "missing",
    }
    with pytest.raises(ValueError, match="research=missing"):
        require_complete_specialists(sample)


@pytest.mark.parametrize("status", ["failed", "cancelled", "timeout", None, "new-status"])
def test_failed_or_unknown_result_cannot_be_accepted_as_complete(status):
    with pytest.raises(ValueError, match="incomplete"):
        require_complete_specialists(messages(status=status))


def test_pending_dispatch_is_distinct_from_missing():
    sample = messages()[:1]
    assert set(specialist_statuses(sample).values()) == {"pending"}


def test_conflicting_dispatch_or_duplicate_result_rejected():
    sample = messages()
    with pytest.raises(ValueError, match="duplicate"):
        specialist_statuses([*sample, sample[1]])
    sample[0]["tool_calls"].append(
        {"name": "task", "id": "another", "args": {"subagent_type": "lab"}}
    )
    with pytest.raises(ValueError, match="ambiguous"):
        specialist_statuses(sample)
