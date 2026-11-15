"""Deterministic negative checks; run in the pinned backend environment."""

from types import SimpleNamespace

from langchain_core.messages import HumanMessage
from p2_agent_budget_guard import P2AgentBudgetGuard as Guard


def verify():
    def request(**updates):
        values = {
            "model": SimpleNamespace(
                model_name="gpt-6-luna",
                use_responses_api=True,
                max_retries=0,
                max_tokens=Guard.OUTPUT_TOKENS,
                root_client=SimpleNamespace(base_url="https://api.openai.com/v1/"),
            ),
            "response_format": None,
            "model_settings": {},
            "system_message": None,
            "messages": [HumanMessage(content="bounded")],
            "tools": [],
        }
        values.update(updates)
        return SimpleNamespace(**values)

    def rejected(candidate):
        before = len(Guard.admissions)
        try:
            Guard()._admit(candidate)
        except RuntimeError:
            assert len(Guard.admissions) == before
        else:
            raise AssertionError("Unsafe request admitted")

    Guard.admissions.clear()
    rejected(request(messages=[HumanMessage(content="x" * 90001)]))
    rejected(
        request(
            messages=[
                HumanMessage(
                    content=[
                        {"type": "image_url", "image_url": {"url": "https://example.com/image"}}
                    ]
                )
            ]
        )
    )
    rejected(request(model_settings={"max_output_tokens": 999999}))
    rejected(request(model_settings={"extra_body": {"model": "other"}}))
    rejected(request(tools=[SimpleNamespace(name="bash")]))
    bad_endpoint = request()
    bad_endpoint.model.root_client.base_url = "https://untrusted.invalid/"
    rejected(bad_endpoint)
    assert Guard._text_content([{"type": "text", "text": "OK", "annotations": []}])
    assert Guard._text_content(
        [{"type": "function_call", "name": "task", "arguments": "{}", "call_id": "fixed"}]
    )
    assert not Guard._text_content([{"type": "text", "text": "OK", "image": "bad"}])
    for _ in range(Guard.MAX_CALLS):
        Guard()._admit(request())
    rejected(request())
    Guard.admissions.clear()
    Guard.outcomes.clear()
    print(
        f"GUARD_NEGATIVE_CHECKS_PASS; shared_call_cap={Guard.MAX_CALLS}; reserved_usd="
        + str(Guard.RESERVED_USD)
    )


if __name__ == "__main__":
    verify()
