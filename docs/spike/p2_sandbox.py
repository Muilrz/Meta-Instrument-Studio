"""Pinned official AIO deployment for the single-purpose P2 test Gateway."""

import copy
import json
import os
import subprocess
from pathlib import Path

from p2e_budget_limits import INPUT_TOKEN_BOUND, MAX_CALLS, OUTPUT_TOKENS

AIO_IMAGE = "enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:1.11.0"
PROXY_IMAGE = "ghcr.io/bytedance/deer-flow-sandbox-network-proxy:latest"
ROLE = "p2-sandbox"


def docker_environment():
    directory = Path("C:/Program Files/Docker/Docker/resources/bin")
    os.environ["PATH"] = str(directory) + os.pathsep + os.environ["PATH"]
    os.environ["DEER_FLOW_SANDBOX_BIND_HOST"] = "127.0.0.1"
    os.environ["NO_PROXY"] = "localhost,127.0.0.1," + os.environ.get("NO_PROXY", "")


def image_digest(image):
    result = subprocess.run(
        ["docker", "image", "inspect", image, "--format", "{{json .RepoDigests}}"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    values = json.loads(result.stdout)
    if values:
        assert "@sha256:" in values[0]
        return values[0]
    # Official proxy Dockerfile built locally from the fixed upstream commit.
    assert image == "mis-p2-network-proxy:58fc5bd"
    result = subprocess.run(
        ["docker", "image", "inspect", image, "--format", "{{.Id}}"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert result.stdout.strip().startswith("sha256:")
    return result.stdout.strip()


def configure(config):
    docker_environment()
    result = subprocess.run(
        ["docker", "info", "--format", "{{.OSType}}"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert result.stdout.strip() == "linux"
    # Native cumulative token limits must cover the same finite task as Guard.
    # The inherited 8k/192 limits belonged to the earlier single-call smoke.
    config["token_budget"] = {
        "enabled": True,
        "max_input_tokens": MAX_CALLS * INPUT_TOKEN_BOUND,
        "max_output_tokens": MAX_CALLS * OUTPUT_TOKENS,
        "max_tokens": MAX_CALLS * (INPUT_TOKEN_BOUND + OUTPUT_TOKENS),
    }
    config["sandbox"] = {
        "use": "deerflow.community.aio_sandbox:AioSandboxProvider",
        "image": image_digest(AIO_IMAGE),
        "port": 18080,
        "replicas": 3,
        "container_prefix": "mis-p2-sandbox",
        "allow_host_bash": False,
        "prewarm": False,
        "mounts": [],
        "environment": {},
        "network": {
            "mode": "isolated",
            "approval": "deny",
            "proxy_image": image_digest(os.environ.get("MIS_P2_PROXY_IMAGE", PROXY_IMAGE)),
        },
    }
    roles = config["authorization"]["provider"]["config"]["roles"]
    roles[ROLE] = copy.deepcopy(roles["user"])
    roles[ROLE]["sandbox"] = {"allow": "*"}
    assert roles["user"]["sandbox"]["allow"] is False


def grant_test_account(runtime_url, user_id, email):
    """Authorized role assignment, scoped to the freshly registered P2 account.

    Uses the existing runtime service credential, not owner or schema grants.
    All ordinary users retain their original Sandbox denial.
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(runtime_url.set(drivername="postgresql+psycopg"), hide_parameters=True)
    try:
        with engine.begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE users SET system_role=:role WHERE id=:id AND email=:email "
                    "AND system_role='user' RETURNING id"
                ),
                {"role": ROLE, "id": user_id, "email": email},
            )
            assert result.scalar_one() == user_id
    finally:
        engine.dispose()
