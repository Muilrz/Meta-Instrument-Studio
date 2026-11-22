"""Deploy and check the pinned native AIO backend before spending model budget."""

import json
import subprocess
import sys
from pathlib import Path

from p2_sandbox import configure

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO.parent / "deer-flow-p2-0a-filtered/backend"))


def main():
    from deerflow.community.aio_sandbox.backend import wait_for_sandbox_ready
    from deerflow.community.aio_sandbox.local_backend import LocalContainerBackend

    config = {
        "authorization": {
            "provider": {"config": {"roles": {"user": {"sandbox": {"allow": False}}}}}
        }
    }
    configure(config)
    settings = config["sandbox"]
    backend = LocalContainerBackend(
        image=settings["image"],
        base_port=settings["port"],
        container_prefix="mis-p2-preflight",
        config_mounts=[],
        environment={},
        network_config=settings["network"],
    )
    info = backend.create(thread_id="p2-preflight", sandbox_id="container-ready", extra_mounts=[])
    try:
        assert wait_for_sandbox_ready(info.sandbox_url, timeout=90, headers=info.request_headers)
        result = subprocess.run(
            ["docker", "inspect", info.container_name],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        item = json.loads(result.stdout)[0]
        host = item["HostConfig"]
        assert not host["Privileged"] and host["Memory"] > 0 and host["NanoCpus"] > 0
        assert host["PidsLimit"] > 0 and "ALL" in host["CapDrop"]
        assert "no-new-privileges" in " ".join(host["SecurityOpt"])
        assert not any(m["Type"] == "bind" for m in item["Mounts"])
        networks = list(item["NetworkSettings"]["Networks"])
        assert len(networks) == 1
        result = subprocess.run(
            ["docker", "network", "inspect", networks[0]],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        assert json.loads(result.stdout)[0]["Internal"] is True
        report = {
            "ready": True,
            "model_calls": 0,
            "sandbox": settings,
            "container_id": item["Id"],
            "memory": host["Memory"],
            "nano_cpus": host["NanoCpus"],
            "pids": host["PidsLimit"],
            "privileged": False,
            "internal_network": True,
            "host_mounts": [],
        }
        path = REPO.parent / "mis-p2-gateway-evidence/sandbox-0f-preflight.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))
    finally:
        backend.destroy(info)


if __name__ == "__main__":
    main()
