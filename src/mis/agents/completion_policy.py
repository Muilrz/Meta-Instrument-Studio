"""JSON-only native completion policy. No MIS database, units or execution engine."""

import hashlib
import json
from typing import Any

from mis.agents.profiles import SPECIALISTS
from mis.agents.results import specialist_statuses


def load_raw_assignments(values):
    if not isinstance(values, list) or len(values) != 3:
        raise ValueError("exactly three authorized assignments required")
    result = {}
    identities = set()
    scopes = set()
    for value in values:
        brief = value["brief"]
        role = brief["specialist"]
        if role not in SPECIALISTS or role in result or brief.get("status") == "stale":
            raise ValueError("invalid assigned role")
        if brief.get("budget", {}).get("model_calls") != 1:
            raise ValueError("required Specialist must have one allocated model call")
        identity = brief["id"]
        if not isinstance(identity, str) or not identity or identity in identities:
            raise ValueError("invalid assigned identity")
        identities.add(identity)
        scopes.add((brief["project_id"], brief["baseline_version"]))
        if not value["evidence"] or any(
            e["project_id"] != brief["project_id"] for e in value["evidence"]
        ):
            raise ValueError("cross-project or missing evidence")
        result[role] = value
    if len(scopes) != 1:
        raise ValueError("bundle scope mismatch")
    return result


def assignment_prompt(value):
    brief = value["brief"]
    return json.dumps(
        {
            **value,
            "result_contract": {
                "role": brief["specialist"],
                "task_id": brief["id"],
                "instructions": "Return only JSON with role, task_id, summary, "
                "claims and unknowns. "
                "Each claim has statement, subject, metric, value. Use value "
                "{kind:known,value:{value:number,unit:string},evidence_ids:[ID]} or "
                "{kind:unknown,reason:string,evidence_ids:[]}. Report each specified parameter "
                "using only assigned evidence. Preserve exact evidence IDs and units. No tools.",
            },
        },
        ensure_ascii=True,
        sort_keys=True,
    )


def execution_report(messages, *, lead_final: bool) -> dict[str, Any]:
    raw = specialist_statuses(messages)
    roles = {
        role: (
            state
            if state in {"completed", "missing"}
            else "failed"
            if state in {"failed", "cancelled", "timed_out", "timeout", "error"}
            else "missing"
        )
        for role, state in raw.items()
    }
    if all(s == "completed" for s in roles.values()) and lead_final:
        overall = "completed"
    elif any(s == "completed" for s in roles.values()):
        overall = "partial"
    elif any(s == "failed" for s in roles.values()):
        overall = "failed"
    else:
        overall = "missing"
    return {"status": overall, "roles": roles, "native_statuses": raw, "lead_final": lead_final}


def complete_summary(content) -> bool:
    """A final label is insufficient; the summary must explicitly cover all roles."""
    if isinstance(content, list):
        content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
    try:
        if content.startswith("```json\n") and content.rstrip().endswith("```"):
            content = content.strip()[8:-3]
        value = json.loads(content)
        roles = value["roles"]
        names = [r if isinstance(r, str) else r["role"] for r in roles]
        summaries = value.get("summaries")
        if (
            summaries is None
            and isinstance(roles, list)
            and all(isinstance(r, dict) for r in roles)
        ):
            summaries = {r["role"]: r.get("summary") for r in roles}
        return (
            len(names) == 3
            and set(names) == set(SPECIALISTS)
            and isinstance(summaries, dict)
            and set(summaries) == set(SPECIALISTS)
            and all(isinstance(s, str) and s.strip() for s in summaries.values())
        )
    except (ValueError, TypeError, KeyError):
        return False


def blocked_response(message):
    extra = message.get("additional_kwargs") or {}
    metadata = message.get("response_metadata") or {}
    if any(
        extra.get(key)
        for key in ("deerflow_error_fallback", "safety_termination", "model_length_termination")
    ):
        return True
    for key in ("finish_reason", "stop_reason", "status"):
        if str(metadata.get(key, "")).lower() in {
            "length",
            "content_filter",
            "safety",
            "refusal",
            "failed",
            "incomplete",
            "cancelled",
            "max_tokens",
        }:
            return True
    content = message.get("content")
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "refusal" for b in content
    )


def complete_calls(assignments, prior_messages, proposed_calls, *, repairs: int, run_id: str):
    """Return canonical native calls, plus at most one business completion batch.

    Never create results, retry failed roles, run tools or start model handlers.
    A partial normal batch is left alone. Only premature finalization triggers
    deterministic calls for still-missing roles. Original provider output remains
    in model telemetry; injected call IDs explicitly identify the MIS contract.
    """
    by_role = load_raw_assignments(assignments)
    states = specialist_statuses(prior_messages)
    calls, seen, origins = [], set(), {}
    for call in proposed_calls:
        args = call.get("args") or {}
        role = args.get("subagent_type")
        if (
            call.get("name") != "task"
            or role not in by_role
            or role in seen
            or states[role] != "missing"
            or not call.get("id")
            or args.get("context_mode", "isolated") != "isolated"
            or args.get("model_name") is not None
        ):
            raise ValueError("illegal, duplicate or repeated Specialist dispatch")
        seen.add(role)
        calls.append(
            {
                "name": "task",
                "id": call["id"],
                "type": "tool_call",
                "args": {
                    "subagent_type": role,
                    "context_mode": "isolated",
                    "description": "MIS assigned " + role,
                    "prompt": assignment_prompt(by_role[role]),
                },
            }
        )
        origins[call["id"]] = "lead"
    missing = [role for role in SPECIALISTS if states[role] == "missing"]
    repaired = False
    if not calls and missing and repairs < 1:
        repaired = True
        for role in missing:
            seed = json.dumps([run_id, by_role[role]["brief"]["id"]], separators=(",", ":"))
            identifier = "mis-required-" + hashlib.sha256(seed.encode()).hexdigest()[:24]
            calls.append(
                {
                    "name": "task",
                    "id": identifier,
                    "type": "tool_call",
                    "args": {
                        "subagent_type": role,
                        "context_mode": "isolated",
                        "description": "MIS required " + role,
                        "prompt": assignment_prompt(by_role[role]),
                    },
                }
            )
            origins[identifier] = "mis_required_brief"
    return calls, origins, repaired
