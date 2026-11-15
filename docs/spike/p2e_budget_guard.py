"""P2-0E single-process shared guard; no authority comes from a model prompt."""

import p2e_budget_limits as limits
from p2_agent_budget_guard import P2AgentBudgetGuard


class P2EGuard(P2AgentBudgetGuard):
    MAX_CALLS = limits.MAX_CALLS
    PRIOR_OCCUPANCY_USD = limits.PRIOR_OCCUPANCY_USD
    RESERVED_USD = limits.RESERVED_USD

    def _admit(self, request):
        messages = ([request.system_message] if request.system_message else []) + list(
            request.messages
        )
        text = "\n".join(str(m.content) for m in messages if getattr(m, "type", None) == "system")
        specialist = any(
            f"You are MIS {r} Specialist." in text for r in ("lab", "research", "procurement")
        )
        names = [getattr(t, "name", None) for t in request.tools]
        if names != ([] if specialist else ["task"]):
            raise RuntimeError("P2-0E tool boundary rejected")
        return super()._admit(request)
