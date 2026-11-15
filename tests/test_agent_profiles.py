from mis.agents import LEAD_NAME, SPECIALISTS, deerflow_profiles


def test_native_profiles_deny_nested_tools_and_limit_catalog():
    profiles = deerflow_profiles()
    assert profiles["lead_config"]["name"] == LEAD_NAME
    assert profiles["lead_config"]["allowed_subagents"] == list(SPECIALISTS)
    assert profiles["lead_config"]["memory_enabled"] is False
    for role, config in profiles["deployment"]["subagents"]["custom_agents"].items():
        assert role in SPECIALISTS
        assert config["tools"] == config["skills"] == []
        assert "task" in config["disallowed_tools"]
        assert config["max_turns"] == 1
        assert "evidence" in config["system_prompt"]
    assert "context_mode=isolated" in profiles["lead_soul"]


def test_profile_documents_are_not_shared_mutable_state():
    profiles = deerflow_profiles()
    profiles["lead_config"]["allowed_subagents"].append("bash")
    profiles["deployment"]["subagents"]["custom_agents"]["lab"]["tools"].append("bash")
    fresh = deerflow_profiles()
    assert "bash" not in fresh["lead_config"]["allowed_subagents"]
    assert fresh["deployment"]["subagents"]["custom_agents"]["lab"]["tools"] == []
