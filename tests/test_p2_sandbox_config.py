"""The P2 account grant must not broaden ordinary users or agent tools."""

import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace


def test_container_permission_is_scoped_and_preserves_tool_boundary(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "docs/spike/p2_sandbox.py"
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location("p2_sandbox_config_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "docker_environment", lambda: None)
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="linux"))
    monkeypatch.setattr(module, "image_digest", lambda image: image + "@sha256:" + "a" * 64)
    user = {"sandbox": {"allow": False}, "tools": {"allow": ["task"]}, "skills": {"allow": False}}
    config = {"authorization": {"provider": {"config": {"roles": {"user": copy.deepcopy(user)}}}}}
    module.configure(config)
    roles = config["authorization"]["provider"]["config"]["roles"]
    assert roles["user"] == user
    assert roles[module.ROLE] == {**user, "sandbox": {"allow": "*"}}
    roles[module.ROLE]["tools"]["allow"].append("test-only")
    assert roles["user"] == user
    sandbox = config["sandbox"]
    assert sandbox["network"]["mode"] == "isolated"
    assert sandbox["network"]["approval"] == "deny"
    assert sandbox["mounts"] == [] and sandbox["environment"] == {}
    assert sandbox["allow_host_bash"] is False and sandbox["prewarm"] is False
    assert config["token_budget"] == {
        "enabled": True,
        "max_input_tokens": 687344,
        "max_output_tokens": 7168,
        "max_tokens": 694512,
    }
