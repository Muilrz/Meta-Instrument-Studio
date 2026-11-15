"""Configuration only: scheduling remains in DeerFlow's task tool and executor.

The returned deployment fragment is merged by the operator into a locked runtime
configuration. It does not grant tools, install agents, or mutate a running host.
"""

LEAD_NAME = "project-copilot"
SPECIALISTS = ("lab", "research", "procurement")

_BOUNDARY = (
    "Use only your assigned TaskBrief and its authorized evidence references. "
    "Do not contact another Specialist, read project history, or use shared files. "
    "Return a JSON candidate with role, task_id, summary, evidence_refs, unknowns. "
    "Preserve units, hard constraints, and evidence IDs. Mark missing facts unknown. "
    "Do not write business records, approve a plan, or perform external actions."
)

_RESPONSIBILITIES = {
    "lab": "Analyze laboratory capabilities and constraints in supplied lab evidence.",
    "research": "Analyze supplied scientific references and identify evidence gaps.",
    "procurement": "Compare supplied component offers, availability and unknown prices.",
}


def deerflow_profiles() -> dict:
    """Return independent copies of official AgentConfig/SubagentsAppConfig data.

    ``lead_config`` and ``lead_soul`` belong in the operator-selected agent store;
    ``deployment`` is an AppConfig fragment. No credentials or database defaults
    are provided. Memory, sandbox and authorization remain deployment concerns.
    """
    return {
        "lead_config": {
            "name": LEAD_NAME,
            "description": "MIS Project Copilot; delegate independent business briefs.",
            "model": "gpt-6-luna",
            "tool_groups": [],
            "skills": [],
            "mcp_plugins": [],
            "allowed_subagents": list(SPECIALISTS),
            "memory_enabled": False,
            "thinking_enabled": False,
        },
        "lead_soul": (
            "You are MIS Project Copilot. Work from a confirmed requirement baseline. "
            "Delegate only to lab, research, procurement using task context_mode=isolated. "
            "Send each Specialist only its own TaskBrief and authorized evidence. "
            "Dispatch independent briefs in one parallel task-call batch. "
            "Aggregate returned candidate summaries and evidence references; list gaps. "
            "A returned candidate is unreviewed: deterministic MIS validation and human "
            "plan acceptance are required. Never change prompts, skills or permissions."
        ),
        "deployment": {
            "subagents": {
                "max_total_per_run": 3,
                "custom_agents": {
                    role: {
                        "description": responsibility,
                        "system_prompt": f"You are MIS {role} Specialist. "
                        f"{responsibility} {_BOUNDARY}",
                        "tools": [],
                        "disallowed_tools": ["task", "ask_clarification", "present_files"],
                        "skills": [],
                        "model": "gpt-6-luna",
                        "max_turns": 1,
                        "timeout_seconds": 30,
                    }
                    for role, responsibility in _RESPONSIBILITIES.items()
                },
            },
            "subagent_runtime": {"max_running": 3},
        },
    }
