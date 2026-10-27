"""Check the effective deployment boundary, including Compose overlay merging."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOCKET_DIR = "/run/openscreen-broker"


@pytest.fixture(scope="module")
def compose():
    executable = shutil.which("docker")
    if not executable:
        pytest.skip("Docker Compose CLI is required (no daemon needed)")
    version = subprocess.run(
        [executable, "compose", "version"], capture_output=True, timeout=20
    )
    if version.returncode:
        pytest.skip("Docker Compose plugin is unavailable")
    return [executable, "compose"]


@pytest.mark.parametrize("deployment", ["overlay", "truenas"])
def test_broker_effective_permissions(compose, deployment, tmp_path):
    env = {**os.environ, "OPENSCREEN_DEVICE_GID": "12345"}
    if deployment == "overlay":
        files = [ROOT / "compose.yaml", ROOT / "compose.broker.yaml"]
    else:
        template = (ROOT / "deploy/truenas-broker-app.yaml").read_text("utf-8-sig")
        for key, value in {
            "YOUR_NAS_IP": "192.0.2.10",
            "YOUR_LAN_CIDR": "192.0.2.0/24",
            "YOUR_POOL": "test-pool",
            "YOUR_DEVICE_GID": "12345",
        }.items():
            template = template.replace(key, value)
        path = tmp_path / "compose.yaml"
        path.write_text(template, encoding="utf-8")
        files = [path]
    arguments = [argument for path in files for argument in ("-f", str(path))]
    result = subprocess.run(
        [*compose, "--project-name", "broker-contract", *arguments, "config", "--format", "json"],
        env=env, capture_output=True, text=True, timeout=30, check=True,
    )
    services = json.loads(result.stdout)["services"]
    web, broker = services["openscreen"], services["display-broker"]
    for service in (web, broker):
        assert service["user"] == "10001:10001"
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert not service.get("privileged")
        assert not service.get("cap_add")
        assert not service.get("devices")
    assert not web.get("group_add")
    assert not web.get("device_cgroup_rules")
    assert web["environment"]["OPENSCREEN_BROKER_SOCKET"] == SOCKET_DIR + "/broker.sock"
    web_mounts = {mount["target"]: mount for mount in web["volumes"]}
    assert set(web_mounts) == {"/data", SOCKET_DIR}
    assert web_mounts[SOCKET_DIR]["read_only"] is True
    assert broker["network_mode"] == "none"
    assert not broker.get("ports")
    assert not broker.get("networks")
    assert broker["group_add"] == ["12345"]
    assert set(broker["device_cgroup_rules"]) == {"c 166:* rw", "c 188:* rw"}
    mounts = {mount["target"]: mount for mount in broker["volumes"]}
    assert set(mounts) == {"/host-dev", "/host-sys", SOCKET_DIR}
    for target, source in (("/host-dev", "/dev"), ("/host-sys", "/sys")):
        assert mounts[target]["source"] == source
        assert mounts[target]["read_only"] is True
        assert not mounts[target].get("bind", {}).get("create_host_path", False)
    assert mounts[SOCKET_DIR]["source"] == web_mounts[SOCKET_DIR]["source"]
    assert not mounts[SOCKET_DIR].get("read_only", False)
    assert broker["pids_limit"] == 64
    assert broker["mem_limit"] == str(128 * 1024 * 1024)
    assert float(broker["cpus"]) == 0.5
    assert broker["healthcheck"]["test"][:3] == ["CMD", "python", "-c"]
    assert "uds=" in broker["healthcheck"]["test"][3]
    assert "/healthz" in broker["healthcheck"]["test"][3]
