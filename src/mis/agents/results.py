"""Validate native delegation receipts; Lead prose cannot fill missing results.

Input must come from the trusted Runtime response, not user-supplied messages.
Completion remains distinct from MIS Artifact validation or business acceptance.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from mis.agents.profiles import SPECIALISTS


def specialist_statuses(messages: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    states = dict.fromkeys(SPECIALISTS, "missing")
    calls = {}
    for message in messages:
        if message.get("type") != "ai":
            continue
        for call in message.get("tool_calls") or ():
            if call.get("name") != "task":
                continue
            identifier = call.get("id")
            role = (call.get("args") or {}).get("subagent_type")
            if not identifier or identifier in calls or role not in states:
                raise ValueError("invalid or conflicting native task receipt identity")
            if states[role] != "missing":
                raise ValueError("multiple dispatches for one Specialist are ambiguous")
            calls[identifier] = role
            states[role] = "pending"
    seen = set()
    for message in messages:
        if message.get("type") != "tool":
            continue
        identifier = message.get("tool_call_id")
        if identifier not in calls:
            continue
        if identifier in seen:
            raise ValueError("duplicate native task result")
        seen.add(identifier)
        status = (message.get("additional_kwargs") or {}).get("subagent_status")
        states[calls[identifier]] = (
            status
            if status in {"completed", "failed", "cancelled", "timed_out", "timeout", "error"}
            else "unknown"
        )
    return states


def require_complete_specialists(messages: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    states = specialist_statuses(messages)
    if any(state != "completed" for state in states.values()):
        detail = ", ".join(f"{role}={state}" for role, state in states.items())
        raise ValueError(f"incomplete specialist results: {detail}")
    return states
